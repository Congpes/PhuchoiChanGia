"""File-backed phone demos; never substitute their measurements for live FSR."""
import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


def install_phone_demo_library(app, root=None):
    root = Path(root) if root is not None else Path(__file__).parent / 'demo_videos'

    def manifest(demo_id):
        if demo_id not in ('phone-01', 'phone-02'):
            raise HTTPException(404, 'Unknown phone demo')
        path = root / demo_id / 'manifest.json'
        if not path.is_file():
            raise HTTPException(404, 'Phone demo has not been imported')
        return json.loads(path.read_text(encoding='utf-8'))

    @app.get('/phone-demos')
    def list_phone_demos():
        return [manifest(name) for name in ('phone-01', 'phone-02')
                if (root / name / 'manifest.json').is_file()]

    @app.get('/phone-demos/{demo_id}')
    def get_phone_demo(demo_id: str):
        return manifest(demo_id)

    @app.get('/phone-demos/{demo_id}/{view}.mp4')
    def phone_demo_video(demo_id: str, view: str):
        manifest(demo_id)
        if view not in ('frontal', 'sagittal'):
            raise HTTPException(404, 'Unknown camera view')
        path = root / demo_id / f'{view}.mp4'
        if not path.is_file():
            raise HTTPException(404, 'Demo video unavailable')
        return FileResponse(path, media_type='video/mp4')

    @app.get('/phone-demos/{demo_id}/simulation')
    def phone_demo_simulation(demo_id: str):
        if demo_id != 'phone-02':
            raise HTTPException(404, 'Simulation available for phone-02 only')
        from phone_demo_simulation import build_simulation
        return build_simulation(manifest(demo_id))
