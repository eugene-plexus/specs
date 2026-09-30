"""Score the shipped starter set for the roadmap's 8 GB GPU / 16 GB RAM case.

This is a capacity fixture, not evidence from a physical 8 GB card. Include
decimal and binary units explicitly rather than silently treating GB as GiB.

The pick either fits entirely on the card, or is a mixture-of-experts entry
whose experts sit in system memory while everything else fits on the card
(moe-aware-fit call B, 2026-09-30). A dense model split across the card and
RAM is never a first model.
"""
import json
from eugene_plexus_library import starter
from eugene_plexus_library._generated.models import MemoryBudget, KvCacheType

results = []
for label, unit in (("GB (decimal)", 10**9), ("GiB (binary)", 1024**3)):
    budget = MemoryBudget(vramFreeBytes=8 * unit, vramTotalBytes=8 * unit,
                         largestGpuFreeBytes=8 * unit, ramAvailableBytes=16 * unit,
                         ramTotalBytes=16 * unit, gpuCount=1, unifiedMemory=False,
                         source="override")
    scored = starter.build(starter.load(), budget=budget, context_length=8192, kv_cache_type=KvCacheType.f16)
    assert scored.recommended and scored.recommended.sizeClass
    selected = next(m for m in scored.models if m.sizeClass == scored.recommended.sizeClass)
    on_card = selected.fit.requiredBytes
    if selected.fit.verdict.value == "fits":
        assert selected.fit.offload is None
    else:
        assert selected.fit.verdict.value in ("tight", "split"), selected.fit.verdict
        assert selected.fit.offload is not None and selected.fit.offload.value == "experts"
        assert selected.fit.expertBytes and selected.fit.requiredBytes <= 24 * unit
        on_card -= selected.fit.expertBytes
    assert on_card <= 8 * unit
    results.append({"capacityUnits": label, "contextTokens": 8192,
                    "recommendedClass": scored.recommended.sizeClass,
                    "model": selected.baseModel, "requiredBytes": selected.fit.requiredBytes,
                    "verdict": selected.fit.verdict.value,
                    "offload": selected.fit.offload.value if selected.fit.offload else None,
                    "onCardBytes": on_card,
                    "reviewed": str(scored.reviewed),
                    "candidates": [{"class": m.sizeClass, "verdict": m.fit.verdict.value,
                                    "requiredBytes": m.fit.requiredBytes} for m in scored.models]})
print(json.dumps(results, indent=2))
