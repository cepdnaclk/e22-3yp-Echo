import numpy as np
from sklearn.neighbors import NearestNeighbors
from typing import List, Optional, Tuple, Dict


class GloveKNNClassifier:
    """
    Baseline KNN Gesture Classifier for Echo smart glove flex sensor readings.
    
    Features:
    - Input: 5-element vector [thumb, index, middle, ring, pinky] normalized to [0, 1]
    - Rejection threshold tau: rejects non-gestures / rest positions if min distance > tau
    - Tie-breaking: uses nearest neighbour (1-NN) in case of a tie vote
    """

    def __init__(self, k: int = 5, tau: float = 0.35):
        """
        :param k: Number of nearest neighbors to inspect.
        :param tau: Distance rejection threshold. Queries further than tau return None ("No gesture").
        """
        self.k = k
        self.tau = tau
        self.classes_: List[str] = []
        self.X_train: Optional[np.ndarray] = None
        self.y_train: Optional[np.ndarray] = None
        self._nn: Optional[NearestNeighbors] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GloveKNNClassifier":
        """
        Store training vectors and labels.
        :param X: Shape (N, 5), scaled flex values in [0, 1] (T, I, M, R, P)
        :param y: Shape (N,), phrase label strings
        """
        self.X_train = np.asarray(X, dtype=np.float32)
        self.y_train = np.asarray(y)
        self.classes_ = sorted(list(set(self.y_train)))

        # Using scikit-learn's NearestNeighbors for Euclidean distance querying
        self._nn = NearestNeighbors(n_neighbors=min(self.k, len(self.X_train)), metric="euclidean")
        self._nn.fit(self.X_train)
        return self

    def predict_one(self, sample: np.ndarray) -> Tuple[Optional[str], float, Dict[str, int]]:
        """
        Classify a single 5-dimensional gesture vector.

        :param sample: Array-like of length 5 [thumb, index, middle, ring, pinky]
        :return: (predicted_phrase or None, nearest_distance, neighbor_vote_counts)
        """
        if self._nn is None or self.X_train is None:
            raise ValueError("Classifier has not been fitted with training data yet.")

        query = np.asarray(sample, dtype=np.float32).reshape(1, -1)
        distances, indices = self._nn.kneighbors(query)
        
        dists = distances[0]
        neighbor_indices = indices[0]
        nearest_dist = float(dists[0])

        # Reject non-gesture or rest pose if minimum distance exceeds tau
        if nearest_dist > self.tau:
            return None, nearest_dist, {}

        # Count votes among k neighbors
        neighbor_labels = self.y_train[neighbor_indices]
        vote_counts: Dict[str, int] = {}
        for label in neighbor_labels:
            vote_counts[label] = vote_counts.get(label, 0) + 1

        # Determine winner; tie-break decided by nearest neighbor (index 0)
        max_votes = max(vote_counts.values())
        top_candidates = [label for label, count in vote_counts.items() if count == max_votes]

        if len(top_candidates) == 1:
            predicted = top_candidates[0]
        else:
            # Tie breaker: choose the top candidate that appears first in the sorted distance list
            for label in neighbor_labels:
                if label in top_candidates:
                    predicted = label
                    break

        return predicted, nearest_dist, vote_counts


def get_sample_phrases_dataset() -> Tuple[np.ndarray, np.ndarray]:
    """
    Provides the 5 baseline placeholder phrases with 2 representative vectors each,
    based on the specification example (T, I, M, R, P; 0 flat, 1 bent).
    """
    dataset = [
        # Hello (open hand)
        ([0.10, 0.05, 0.05, 0.05, 0.10], "Hello"),
        ([0.12, 0.06, 0.04, 0.06, 0.09], "Hello"),
        # Yes (fist)
        ([0.30, 0.90, 0.92, 0.90, 0.88], "Yes"),
        ([0.32, 0.88, 0.90, 0.91, 0.86], "Yes"),
        # Me (index pointing: index flat, other fingers bent)
        ([0.70, 0.05, 0.90, 0.90, 0.88], "Me"),
        ([0.68, 0.07, 0.89, 0.92, 0.87], "Me"),
        # Water (three fingers up: index, middle, ring flat; thumb & pinky bent)
        ([0.80, 0.08, 0.06, 0.07, 0.85], "Water"),
        ([0.79, 0.10, 0.07, 0.09, 0.83], "Water"),
        # Help (thumb and pinky out: index, middle, ring bent)
        ([0.05, 0.90, 0.92, 0.90, 0.08], "Help"),
        ([0.07, 0.88, 0.91, 0.89, 0.10], "Help"),
    ]

    X = np.array([sample[0] for sample in dataset], dtype=np.float32)
    y = np.array([sample[1] for sample in dataset])
    return X, y


if __name__ == "__main__":
    # 1. Load sample dataset
    X_sample, y_sample = get_sample_phrases_dataset()

    # 2. Initialize and fit the classifier with k=3 (for toy dataset) and tau=0.35
    clf = GloveKNNClassifier(k=3, tau=0.35)
    clf.fit(X_sample, y_sample)

    print("--- Baseline Glove KNN Classifier Initialized ---")
    print(f"Stored phrases: {clf.classes_}")

    # 3. Test Query from the design specification:
    # q = [0.78, 0.12, 0.08, 0.15, 0.80] -> Expected to match "Water"
    test_gesture = np.array([0.78, 0.12, 0.08, 0.15, 0.80])
    label, min_dist, votes = clf.predict_one(test_gesture)
    print(f"\n[Test 1 - Gesture Query]")
    print(f"Query: {test_gesture.tolist()}")
    print(f"Nearest Distance: {min_dist:.4f} (tau={clf.tau})")
    print(f"Votes: {votes}")
    print(f"Prediction: {label if label is not None else 'REJECTED (No Gesture)'}")

    # 4. Rest Pose from specification:
    # half-curled hand [0.45, 0.45, 0.45, 0.45, 0.45] -> Expected to be rejected (dist ~0.85 > tau)
    rest_pose = np.array([0.45, 0.45, 0.45, 0.45, 0.45])
    label_rest, min_dist_rest, _ = clf.predict_one(rest_pose)
    print(f"\n[Test 2 - Rest Pose Query]")
    print(f"Query: {rest_pose.tolist()}")
    print(f"Nearest Distance: {min_dist_rest:.4f} (tau={clf.tau})")
    print(f"Prediction: {label_rest if label_rest is not None else 'REJECTED (No Gesture)'}")
