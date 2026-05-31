import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from .tracker import SimpleTracker

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
LAYOUT_PATH = DATA_DIR / "store_layout.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"

CAMERA_ROLE = {
    'CAM 1.mp4': 'entry',
    'CAM 2.mp4': 'entry',
    'CAM 3.mp4': 'floor',
    'CAM 4.mp4': 'floor',
    'CAM 5.mp4': 'billing',
}

ZONE_MAP = {
    'floor': ['SKINCARE', 'MAIN_FLOOR', 'COSMETICS'],
    'billing': ['BILLING'],
}

EVENT_TYPES = {
    'ENTRY',
    'EXIT',
    'ZONE_ENTER',
    'ZONE_EXIT',
    'ZONE_DWELL',
    'BILLING_QUEUE_JOIN',
    'BILLING_QUEUE_ABANDON',
    'PURCHASE',
    'REENTRY',
}


def load_layout() -> Dict[str, Any]:
    if LAYOUT_PATH.exists():
        with LAYOUT_PATH.open('r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def make_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.75,
    metadata: Optional[Dict[str, Any]] = None,
    session_seq: int = 0,
) -> Dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f'Invalid event_type {event_type}')
    enriched_metadata = dict(metadata or {})
    enriched_metadata.setdefault('queue_depth', None)
    enriched_metadata.setdefault('sku_zone', None)
    enriched_metadata['session_seq'] = session_seq
    return {
        'event_id': str(uuid.uuid4()),
        'store_id': store_id,
        'camera_id': camera_id,
        'visitor_id': visitor_id,
        'event_type': event_type,
        'timestamp': timestamp.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
        'zone_id': zone_id,
        'dwell_ms': dwell_ms,
        'is_staff': is_staff,
        'confidence': confidence,
        'metadata': enriched_metadata,
    }


class EventGenerator:
    def __init__(self, store_id: str = 'STORE_BLR_002'):
        self.store_id = store_id
        self.layout = load_layout()
        self.tracker = SimpleTracker()
        self.visitor_state: Dict[str, Dict[str, Any]] = {}
        self.session_counter: Dict[str, int] = {}
        self.recent_entry_events: List[Dict[str, Any]] = []
        self.entry_window = timedelta(seconds=2)

    def _camera_id(self, file_path: Path) -> str:
        file_name = file_path.name
        return self.layout.get('camera_mapping', {}).get(file_name, file_name.replace(' ', '_').replace('.mp4', ''))

    def _estimate_zone(self, role: str, frame_shape: tuple, centroid: tuple) -> Optional[str]:
        if role == 'billing':
            return 'BILLING'
        if role != 'floor':
            return None
        width = frame_shape[1]
        x, _ = centroid
        if x < width * 0.33:
            return 'SKINCARE'
        if x < width * 0.66:
            return 'MAIN_FLOOR'
        return 'COSMETICS'

    def _inc_session_seq(self, visitor_id: str) -> int:
        self.session_counter.setdefault(visitor_id, 0)
        self.session_counter[visitor_id] += 1
        return self.session_counter[visitor_id]

    def _create_state(self, visitor_id: str, timestamp: datetime) -> Dict[str, Any]:
        return {
            'last_zone': None,
            'zone_entered_at': timestamp,
            'last_seen': timestamp,
            'first_seen': timestamp,
            'has_entered': False,
            'has_exited': False,
            'last_exit': None,
            'billing_joined': False,
            'billing_joined_at': None,
            'purchased': False,
            'is_staff': False,
            'session_seq': 0,
        }

    def process_video(self, video_path: Path) -> List[Dict[str, Any]]:
        role = CAMERA_ROLE.get(video_path.name, 'floor')
        camera_id = self._camera_id(video_path)
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        start_time = datetime.now(timezone.utc) - timedelta(minutes=total_frames / fps)
        history: List[Dict[str, Any]] = []

        subtractor = cv2.createBackgroundSubtractorMOG2(history=500, detectShadows=True)
        frame_index = 0
        queue_depth = 0

        def append_event(event_type: str, visitor_id: str, timestamp: datetime, zone_id: Optional[str] = None, dwell_ms: int = 0, metadata: Optional[Dict[str, Any]] = None, session_seq: Optional[int] = None, is_staff: bool = False):
            if session_seq is None:
                session_seq = state['session_seq'] or self._inc_session_seq(str(visitor_id))
                state['session_seq'] = session_seq
            event_idx = len(history)
            history.append(make_event(self.store_id, camera_id, f'VIS_{visitor_id}', event_type, timestamp, zone_id=zone_id, dwell_ms=dwell_ms, is_staff=is_staff, metadata=metadata or {}, session_seq=session_seq))
            return event_idx

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_index % 5 != 0:
                frame_index += 1
                continue
            timestamp = start_time + timedelta(seconds=frame_index / fps)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mask = subtractor.apply(gray)
            _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
            mask = cv2.medianBlur(mask, 5)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            detections = []
            for contour in contours:
                if cv2.contourArea(contour) < 900:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if w < 30 or h < 50:
                    continue
                detections.append((x, y, w, h))
            tracked = self.tracker.update(detections, frame_index)
            for visitor_id, box in tracked.items():
                if visitor_id not in self.visitor_state:
                    self.visitor_state[visitor_id] = self._create_state(visitor_id, timestamp)
                state = self.visitor_state[visitor_id]
                centroid = (box[0] + box[2] // 2, box[1] + box[3] // 2)
                zone = self._estimate_zone(role, frame.shape, centroid)
                state['last_seen'] = timestamp
                if not state['is_staff'] and not state['has_entered'] and not state['has_exited']:
                    if (timestamp - state['first_seen']).total_seconds() > 180:
                        state['is_staff'] = True
                is_staff = state['is_staff']

                if role == 'entry':
                    if centroid[0] > frame.shape[1] * 0.4 and not state['has_entered']:
                        state['has_entered'] = True
                        state['has_exited'] = False
                        state['last_seen'] = timestamp
                        session_seq = self._inc_session_seq(str(visitor_id))
                        state['session_seq'] = session_seq
                        event_idx = append_event('ENTRY', visitor_id, timestamp, metadata={}, session_seq=session_seq, is_staff=is_staff)
                        self.recent_entry_events = [entry for entry in self.recent_entry_events if (timestamp - entry['timestamp']) <= self.entry_window]
                        self.recent_entry_events.append({'timestamp': timestamp, 'index': event_idx})
                        group = [entry for entry in self.recent_entry_events if (timestamp - entry['timestamp']) <= self.entry_window]
                        if len(group) > 1:
                            group_size = len(group)
                            for entry in group:
                                history[entry['index']]['metadata']['group_size'] = group_size
                    elif centroid[0] < frame.shape[1] * 0.25 and state['has_entered'] and not state['has_exited']:
                        state['has_exited'] = True
                        state['last_exit'] = timestamp
                        session_seq = state['session_seq'] or self._inc_session_seq(str(visitor_id))
                        append_event('EXIT', visitor_id, timestamp, metadata={}, session_seq=session_seq, is_staff=is_staff)
                        if state['has_entered'] and state['last_exit'] and (timestamp - state['last_exit']).total_seconds() < 300:
                            session_seq = self._inc_session_seq(str(visitor_id))
                            state['session_seq'] = session_seq
                            state['has_entered'] = True
                            state['has_exited'] = False
                            append_event('REENTRY', visitor_id, timestamp, metadata={}, session_seq=session_seq, is_staff=is_staff)
                else:
                    if zone and zone != state['last_zone']:
                        if state['last_zone']:
                            append_event('ZONE_EXIT', visitor_id, timestamp, zone_id=state['last_zone'], metadata={}, session_seq=None, is_staff=is_staff)
                        state['last_zone'] = zone
                        state['zone_entered_at'] = timestamp
                        if state['session_seq'] == 0:
                            state['session_seq'] = self._inc_session_seq(str(visitor_id))
                        append_event('ZONE_ENTER', visitor_id, timestamp, zone_id=zone, metadata={}, session_seq=state['session_seq'], is_staff=is_staff)
                    elif zone and state['last_zone'] == zone:
                        dwell_ms = int((timestamp - state['zone_entered_at']).total_seconds() * 1000)
                        if dwell_ms >= 30000 and (len(history) == 0 or history[-1]['event_type'] != 'ZONE_DWELL'):
                            if state['session_seq'] == 0:
                                state['session_seq'] = self._inc_session_seq(str(visitor_id))
                            append_event('ZONE_DWELL', visitor_id, timestamp, zone_id=zone, dwell_ms=dwell_ms, metadata={}, session_seq=state['session_seq'], is_staff=is_staff)
                    if role == 'billing':
                        in_billing = centroid[0] > frame.shape[1] * 0.6
                        if in_billing and not state['billing_joined']:
                            if state['session_seq'] == 0:
                                state['session_seq'] = self._inc_session_seq(str(visitor_id))
                            state['billing_joined'] = True
                            state['billing_joined_at'] = timestamp
                            queue_depth = max(queue_depth, sum(1 for e in history if e['event_type'] == 'BILLING_QUEUE_JOIN')) + 1
                            append_event('BILLING_QUEUE_JOIN', visitor_id, timestamp, zone_id='BILLING', metadata={'queue_depth': queue_depth}, session_seq=state['session_seq'], is_staff=is_staff)
                        elif not in_billing and state['billing_joined']:
                            billing_duration = (timestamp - state['billing_joined_at']).total_seconds() if state['billing_joined_at'] else 0
                            state['billing_joined'] = False
                            if billing_duration >= 45:
                                append_event('PURCHASE', visitor_id, timestamp, zone_id='BILLING', metadata={}, session_seq=state['session_seq'], is_staff=is_staff)
                                state['purchased'] = True
                            else:
                                append_event('BILLING_QUEUE_ABANDON', visitor_id, timestamp, zone_id='BILLING', metadata={}, session_seq=state['session_seq'], is_staff=is_staff)
            frame_index += 1
        cap.release()
        return history


if __name__ == '__main__':
    if not LAYOUT_PATH.exists():
        print('Missing store layout config at', LAYOUT_PATH)
    event_generator = EventGenerator()
    video_files = sorted(DATA_DIR.glob('CAM *.mp4'))
    if not video_files:
        print('No video files found in', DATA_DIR)
        raise SystemExit(1)
    all_events: List[Dict[str, Any]] = []
    for video_file in video_files:
        print('Processing', video_file.name)
        all_events.extend(event_generator.process_video(video_file))
    if not all_events:
        print('No events generated')
        raise SystemExit(1)
    with EVENTS_PATH.open('w', encoding='utf-8') as f:
        for event in all_events:
            f.write(json.dumps(event) + '\n')
    print(f'Wrote {len(all_events)} events to {EVENTS_PATH}')
