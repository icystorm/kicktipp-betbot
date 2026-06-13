from .base import PredictorBase
from scipy.optimize import minimize # type: ignore
from scipy.stats import poisson # type: ignore
import numpy as np # type: ignore
import penaltyblog as pb # type: ignore


class PoissonPredictor(PredictorBase):
    MAX_GOALS = 7

    # Dixon-Coles Korrekturterm rho
    RHO = -0.0497  # MLE-Schätzung aus reinen WM-Endrundendaten.

    def calculate_probabilities(self, rate_home, rate_deuce, rate_road):
        return pb.implied.power(
            [rate_home, rate_deuce, rate_road]
        )["implied_probabilities"]

    # ------------------------------------------------------------------
    # Dixon-Coles Korrektur tau(x, y, mu1, mu2, rho)
    # Nur für x,y in {0,1} relevant – höhere Scores vernachlässigbar
    # Quelle: Dixon & Coles (1997), J. Royal Statistical Society
    # ------------------------------------------------------------------
    def _tau(self, x, y, mu1, mu2, rho):
        if x == 0 and y == 0:
            return 1 - mu1 * mu2 * rho
        elif x == 0 and y == 1:
            return 1 + mu1 * rho
        elif x == 1 and y == 0:
            return 1 + mu2 * rho
        elif x == 1 and y == 1:
            return 1 - rho
        return 1.0

    def _score_matrix(self, mu1, mu2):
        """
        Erstellt Wahrscheinlichkeitsmatrix P(X=i, Y=j) mit Dixon-Coles-Korrektur.
        Zeile = Heimtore, Spalte = Auswärtstore.
        """
        mat = np.zeros((self.MAX_GOALS + 1, self.MAX_GOALS + 1))
        for i in range(self.MAX_GOALS + 1):
            for j in range(self.MAX_GOALS + 1):
                p = poisson.pmf(i, mu1) * poisson.pmf(j, mu2)
                p *= self._tau(i, j, mu1, mu2, self.RHO)
                mat[i, j] = p
        # Renormalisieren (Korrektur verändert Summe minimal)
        mat /= mat.sum()
        return mat

    # ------------------------------------------------------------------
    # Log-Likelihood Loss (besser als MSE für Wahrscheinlichkeiten)
    # Minimiert negative Log-Likelihood der beobachteten Win/Draw/Loss-Probs
    # ------------------------------------------------------------------
    def _neg_log_likelihood(self, params, home, draw, away):
        mu1 = np.exp(params[0])
        mu2 = np.exp(params[1])

        mat = self._score_matrix(mu1, mu2)

        p_home = np.sum(np.tril(mat, -1))
        p_draw = np.sum(np.diag(mat))
        p_away = np.sum(np.triu(mat, 1))

        # Clip für numerische Stabilität
        eps = 1e-9
        p_home = np.clip(p_home, eps, 1 - eps)
        p_draw = np.clip(p_draw, eps, 1 - eps)
        p_away = np.clip(p_away, eps, 1 - eps)

        # Negative Log-Likelihood: obs * log(pred)
        # obs sind implied probabilities (kontinuierlich, nicht 0/1)
        nll = -(home * np.log(p_home) +
                draw * np.log(p_draw) +
                away * np.log(p_away))
        return nll

    def goal_expectation(self, home, draw, away):
        res = minimize(
            fun=self._neg_log_likelihood,
            x0=[0.26, 0.07],  # log(mu) Startwerte aus Datenmittelwerten
            args=(home, draw, away),
            method='L-BFGS-B',
            bounds=[(-2, 2), (-2, 2)],  # mu zwischen 0.14 und 7.4
            options={"maxiter": 1000, "disp": False},
        )
        return np.exp(res.x[0]), np.exp(res.x[1])

    def calculate_reward(self, predicted, actual,
                         win_exact_score_points, win_goal_difference_points,
                         win_tendency_points, draw_exact_score_points,
                         draw_tendency_points, quote_points):
        pred_home, pred_away = predicted
        act_home, act_away = actual

        base_reward = 0
        if predicted == actual:
            base_reward = (draw_exact_score_points if act_home == act_away
                           else win_exact_score_points)
        elif (pred_home - pred_away) == (act_home - act_away):
            base_reward = (draw_tendency_points if act_home == act_away
                           else win_goal_difference_points)
        elif ((pred_home > pred_away and act_home > act_away) or
              (pred_home < pred_away and act_home < act_away)):
            base_reward = win_tendency_points

        if act_home > act_away:
            community_odds_points = quote_points[0]
        elif act_home < act_away:
            community_odds_points = quote_points[2]
        else:
            community_odds_points = quote_points[1]

        return base_reward + community_odds_points

    def predict(self, match,
                win_exact_score_points, win_goal_difference_points,
                win_tendency_points, draw_exact_score_points,
                draw_tendency_points, quote_points):

        win_prob, draw_prob, lose_prob = self.calculate_probabilities(
            match.rate_home, match.rate_deuce, match.rate_road
        )
        mu_home, mu_away = self.goal_expectation(win_prob, draw_prob, lose_prob)

        # Wahrscheinlichkeitsmatrix mit Dixon-Coles
        mat = self._score_matrix(mu_home, mu_away)

        best_prediction = (0, 0)
        best_expected_reward = 0.0

        for home_goals in range(self.MAX_GOALS + 1):
            for away_goals in range(self.MAX_GOALS + 1):
                predicted = (home_goals, away_goals)
                expected_reward = 0.0

                for actual_home in range(self.MAX_GOALS + 1):
                    for actual_away in range(self.MAX_GOALS + 1):
                        prob = mat[actual_home, actual_away]
                        reward = self.calculate_reward(
                            predicted, (actual_home, actual_away),
                            win_exact_score_points, win_goal_difference_points,
                            win_tendency_points, draw_exact_score_points,
                            draw_tendency_points, quote_points
                        )
                        expected_reward += prob * reward

                if expected_reward >= best_expected_reward:
                    best_expected_reward = expected_reward
                    best_prediction = predicted

        return best_prediction