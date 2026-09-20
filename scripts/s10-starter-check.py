"""Score the shipped starter set for the roadmap's 8 GB GPU / 16 GB RAM case.

This is a capacity fixture, not evidence from a physical 8 GB card. Include
decimal and binary units explicitly rather than silently treating GB as GiB.
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
    assert selected.fit.verdict.value == "fits"
    assert selected.fit.requiredBytes <= 8 * unit
    results.append({"capacityUnits": label, "contextTokens": 8192,
                    "recommendedClass": scored.recommended.sizeClass,
                    "model": selected.baseModel, "requiredBytes": selected.fit.requiredBytes,
                    "reviewed": str(scored.reviewed),
                    "candidates": [{"class": m.sizeClass, "verdict": m.fit.verdict.value,
                                    "requiredBytes": m.fit.requiredBytes} for m in scored.models]})
print(json.dumps(results, indent=2))
