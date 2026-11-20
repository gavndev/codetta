"""The first-run setup steps."""
from __future__ import annotations

from fastapi import HTTPException

from codetta.core.onboarding import OnboardingStore


def register(app, shared) -> None:
    connections = shared.connections
    settings = shared.settings

    onboarding = OnboardingStore(settings.config_dir / "onboarding.json")

    @app.get("/api/onboarding")
    def get_onboarding() -> dict:
        """Setup steps still to show (new installs: all; after an update: only new ones)."""
        steps = []
        if connections.needs_choice:
            steps.append("connections")
        steps += [s for s in ("organize", "library", "inbox", "health", "slskd") if s not in onboarding.done]
        return {"steps": steps}

    @app.post("/api/onboarding/{step}")
    def finish_onboarding_step(step: str) -> dict:
        if step == "connections":
            return get_onboarding()  # finished by saving the connections
        try:
            onboarding.mark(step)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_onboarding()
