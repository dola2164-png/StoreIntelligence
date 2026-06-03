from typing import Dict, List, Tuple, Any


class SimpleTracker:
    def __init__(self, max_distance: int = 80, max_lost: int = 25):
        self.next_id = 1
        self.objects: Dict[int, Tuple[int, int, int, int]] = {}
        self.last_seen: Dict[int, int] = {}
        self.lost_objects: Dict[int, Dict[str, Any]] = {}
        self.max_distance = max_distance
        self.max_lost = max_lost

    @staticmethod
    def _centroid(box):
        x, y, w, h = box
        return x + w // 2, y + h // 2

    @staticmethod
    def _distance(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def update(self, detections: List[Tuple[int, int, int, int]], frame_index: int):
        assigned = {}
        remaining = set(self.objects.keys())
        det_centroids = [self._centroid(d) for d in detections]

        for det_idx, box in enumerate(detections):
            centroid = det_centroids[det_idx]
            best_id = None
            best_dist = self.max_distance
            for obj_id in list(remaining):
                existing_centroid = self._centroid(self.objects[obj_id])
                dist = self._distance(centroid, existing_centroid)
                if dist < best_dist:
                    best_dist = dist
                    best_id = obj_id
            if best_id is None:
                # Attempt a simple re-ID against recently lost tracks
                for obj_id, lost in list(self.lost_objects.items()):
                    if frame_index - lost['last_seen'] > self.max_lost * 4:
                        del self.lost_objects[obj_id]
                        continue
                    existing_centroid = self._centroid(lost['box'])
                    dist = self._distance(centroid, existing_centroid)
                    if dist < best_dist:
                        best_dist = dist
                        best_id = obj_id
                if best_id is None:
                    assigned_id = self.next_id
                    self.next_id += 1
                else:
                    assigned_id = best_id
                    del self.lost_objects[best_id]
                self.objects[assigned_id] = box
                self.last_seen[assigned_id] = frame_index
                assigned[assigned_id] = box
            else:
                self.objects[best_id] = box
                self.last_seen[best_id] = frame_index
                assigned[best_id] = box
                remaining.discard(best_id)

        for obj_id in list(remaining):
            if frame_index - self.last_seen.get(obj_id, frame_index) > self.max_lost:
                self.lost_objects[obj_id] = {
                    'box': self.objects[obj_id],
                    'last_seen': self.last_seen[obj_id],
                }
                del self.objects[obj_id]
                del self.last_seen[obj_id]

        return assigned
