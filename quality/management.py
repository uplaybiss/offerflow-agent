from __future__ import annotations

import re
from typing import Any

from core.errors import NotFoundError, ValidationError
from quality.contract_scenarios import AgentContractScenarioEvaluator
from quality.eval import FixedEvalService
from quality.scenarios import FixedScenarioEvaluator
from quality.store import QualityStore


BASELINE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")


class QualityManagementService:
    def __init__(self, store: QualityStore, evaluation: FixedEvalService, contract_evaluation: Any, agentops: Any) -> None:
        self.store = store
        self.evaluation = evaluation
        self.contract_evaluation = contract_evaluation
        self.agentops = agentops

    @staticmethod
    def _baseline(value: Any) -> str:
        name = str(value or "phase5-stable").strip()
        if not BASELINE_PATTERN.fullmatch(name):
            raise ValidationError("baseline_name 需为 3-64 位字母、数字或 ._:-")
        return name

    def run_fixed(self, payload: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
        baseline_name = self._baseline(payload.get("baseline_name"))
        state = self.agentops.store.release_state()
        config_version_id = state["stable_version_id"]
        with FixedScenarioEvaluator() as scenario:
            if replay:
                return self.evaluation.replay(
                    scenario.evaluate,
                    baseline_name=baseline_name,
                    config_version_id=config_version_id,
                )
            return self.evaluation.run(
                scenario.evaluate,
                baseline_name=baseline_name,
                update_baseline=bool(payload.get("update_baseline", False)),
                config_version_id=config_version_id,
            )

    def trace(self, trace_id: str) -> dict[str, Any]:
        result = self.store.trace_summary(trace_id)
        if not result:
            raise NotFoundError("Trace 不存在")
        return result

    def run_contract(self) -> dict[str, Any]:
        state = self.agentops.store.release_state()
        with AgentContractScenarioEvaluator() as scenario:
            return self.contract_evaluation.run(
                scenario.evaluate,
                config_version_id=state["stable_version_id"],
            )

    def evaluation_run(self, eval_run_id: str) -> dict[str, Any]:
        result = self.store.get_eval_run(eval_run_id)
        if not result:
            raise NotFoundError("评测运行不存在")
        return result
