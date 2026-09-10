"""HTTP facade for the experimental shared authoring domain."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from lib.authoring_studio import Studio, StudioError
from lib.authoring_studio.generator import Generator
from lib.authoring_studio.models import Command, CreateFeature, DeleteFeature
from lib.authoring_studio.service import markdown
from lib.authoring_studio.editable_markdown import editable_markdown
from lib.authoring_studio.reviews import saved_reviews


class StudioAPI:
    def __init__(self, project_root: Path):
        self.studio = Studio(project_root)
        self.generator = Generator(project_root)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="authoring-studio")
        self.router = APIRouter(prefix="/studio", tags=["Authoring studio experiment"])
        self._routes()

    def recover(self):
        self.studio.recover()

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except StudioError as error:
            raise HTTPException(status_code=error.status, detail=str(error)) from error

    def _schedule(self, state):
        for operation in state["operations"]:
            if operation["status"] == "queued":
                self.executor.submit(self.studio.run, state["id"], operation["id"], self.generator)
        return state

    def _routes(self):
        @self.router.get("/health")
        def health():
            return {"status": "ok", "contract": 1, "project_root": str(self.studio.root)}

        @self.router.get("/features")
        def features():
            return self.studio.list()

        @self.router.post("/features", status_code=201)
        def create(request: CreateFeature):
            return self._schedule(self._call(self.studio.create, request))

        @self.router.get("/features/{feature_id}")
        def get(feature_id: str):
            return self._call(self.studio.get, feature_id)

        @self.router.delete("/features/{feature_id}")
        def delete(feature_id: str, request: DeleteFeature):
            return self._call(self.studio.delete, feature_id, request.expected_revision)

        @self.router.post("/features/{feature_id}/commands")
        def command(feature_id: str, request: Command):
            return self._schedule(self._call(self.studio.command, feature_id, request))

        @self.router.get("/features/{feature_id}/versions/{version_id}")
        def version(feature_id: str, version_id: str):
            return self._call(self.studio.version, feature_id, version_id)

        @self.router.get("/features/{feature_id}/versions/{version_id}/markdown")
        def export(feature_id: str, version_id: str):
            state = self._call(self.studio.get, feature_id)
            snapshot = self._call(self.studio.version, feature_id, version_id)
            return Response(markdown(snapshot, state["title"], saved_reviews(state['documents'][snapshot['kind']], version_id)), media_type="text/markdown",
                            headers={"Content-Disposition": f'attachment; filename="{snapshot["kind"]}-v{snapshot["number"]}.md"'})

        @self.router.get("/features/{feature_id}/versions/{version_id}/editable")
        def editable(feature_id: str, version_id: str):
            snapshot = self._call(self.studio.version, feature_id, version_id)
            return {"markdown": editable_markdown(snapshot)}
