import tempfile
import unittest
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Fault, InjectedFailure
from pipelines.etl.pipeline import IncrementalETL
from pipelines.etl.policy import BatchPolicy
from scripts.fixtures import order_event
from scripts.load_eval import full_recompute


class BatchPolicyTests(unittest.TestCase):
    def test_quiet_steady_and_burst_sizes(self):
        policy = BatchPolicy()
        self.assertEqual((100, "quiet"), policy.select(50))
        self.assertEqual((500, "normal"), policy.select(1500))
        self.assertEqual((1000, "burst"), policy.select(10000))

    def test_slow_processing_reduces_new_batch_size(self):
        self.assertEqual((500, "burst-pressure-limited"), BatchPolicy().select(10000, 1.0))
        self.assertEqual((100, "quiet-pressure-limited"), BatchPolicy().select(50, 1.0))

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            BatchPolicy(quiet_size=1000, normal_size=100)
        with self.assertRaises(ValueError):
            BatchPolicy(slow_seconds=0)

    def test_adaptive_worker_keeps_pinned_batch_after_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, warehouse = Source(root / "s.db"), Warehouse(root / "w.db")
            warehouse.authorize_many(
                source.name, [(f"ORDER-{i}", "CUSTOMER-A", "PROJECT-A") for i in range(250)]
            )
            source.append([order_event(f"ORDER-{i}") for i in range(250)])
            worker = IncrementalETL(
                source,
                warehouse,
                policy=BatchPolicy(
                    quiet_size=10, normal_size=100, burst_size=200, burst_backlog=300
                ),
            )
            with self.assertRaises(InjectedFailure):
                worker.run_once(Fault("after_stage"))
            restarted = IncrementalETL(
                source,
                warehouse,
                policy=BatchPolicy(quiet_size=1, normal_size=2, burst_size=3, burst_backlog=4),
            )
            result = restarted.run_once()
            self.assertEqual("pinned-recovery", result["batch_policy"]["mode"])
            self.assertEqual(100, result["metrics"]["input_rows"])
            self.assertEqual(100, warehouse.cursor(source.name))

    def test_independent_oracle_has_known_values(self):
        inputs = [order_event("ONE", quantity=3, unit_cost="1.10", unit_price="2.30")]
        self.assertEqual({"ONE": [1, 3, 330, 690, "D1"]}, full_recompute(inputs))


if __name__ == "__main__":
    unittest.main()
