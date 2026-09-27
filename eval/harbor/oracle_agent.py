import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.installed.base import BaseInstalledAgent, EnvVar, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

REPO = Path(__file__).resolve().parents[2]
REMOTE = "/opt/oracle"
FORWARDED = ("LLM_BASE_URL", "LLM_API_KEY", "GEMINI_API_KEY", "LLM_SUMMARIZER_MODEL")


class OracleAgent(BaseInstalledAgent):
    ENV_VARS = [
        EnvVar("max_tool_steps", "MAX_TOOL_STEPS", type="int"),
        EnvVar("investigation_timeout", "ORACLE_TIMEOUT", type="int"),
        *(EnvVar(key.lower(), key, env_fallback=key) for key in FORWARDED),
    ]

    @staticmethod
    def name() -> str:
        return "marconi-oracle"

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(environment, f"mkdir -p {REMOTE}/eval")
        for item in ("pyproject.toml", "uv.lock", "README.md"):
            await environment.upload_file(REPO / item, f"{REMOTE}/{item}")
        await environment.upload_dir(REPO / "src", f"{REMOTE}/src")
        await environment.upload_dir(REPO / "eval" / "harbor", f"{REMOTE}/eval/harbor")
        await self.exec_as_root(
            environment,
            f"cd {REMOTE} && uv sync --frozen --no-dev",
            env={"UV_LINK_MODE": "copy"},
        )

    @with_prompt_template
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        provider, _, model = (self.model_name or "").partition("/")
        if not model:
            raise ValueError("pass the model as -m provider/model, e.g. -m openai/marconi-llm")
        env = self.resolve_env_vars() | {
            "LLM_PROVIDER": "google" if provider in ("google", "gemini") else "openai",
            "LLM_MODEL": model,
            "DATABASE_URL": "sqlite:////tmp/oracle/agent.db",
        }
        await self.exec_as_agent(
            environment,
            f"printf %s {shlex.quote(instruction)} | "
            f"{REMOTE}/.venv/bin/python {REMOTE}/eval/harbor/run_oracle.py",
            env=env,
            cwd=REMOTE,
        )


class NullAgent(BaseAgent):
    """Answers without looking. Every task must score correct=0 against it."""

    @staticmethod
    def name() -> str:
        return "null"

    def version(self) -> str:
        return "1"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        await environment.exec(
            "mkdir -p /logs/agent/oracle && echo 'I am not sure.' > /logs/agent/oracle/answer.md"
            " && echo '[]' > /logs/agent/oracle/trajectory.json"
        )
