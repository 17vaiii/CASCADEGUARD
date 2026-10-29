"""Person 2 / R3: build graph tensors from a cascade scenario snapshot.

Input schema: contracts/CASCADE_SCENARIOS.md plus the agreed bus/line snapshot
features. Output: a PyTorch Geometric Data or HeteroData object. Keep feature
ordering and normalization in this module documented and versioned.
"""


def build_graph(snapshot):
    """Convert one network snapshot into the model's graph representation."""
    raise NotImplementedError("Person 2: implement the R3 cascade graph builder")
