"""Person 2 / R4: cascade GNN training and inference interface."""


class CascadePredictor:
    """Predict line failures, cascade extent, and Bengaluru load loss."""

    def predict(self, graph):
        """Return a response conforming to contracts/CASCADE_PREDICTION.md."""
        raise NotImplementedError("Person 2: implement the R4 cascade predictor")
