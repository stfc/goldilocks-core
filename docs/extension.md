# Extension guide

How to extend goldilocks-core with new capabilities while preserving stage boundaries.

## Adding a new DFT code generator

1. Create a new generation function in `generation.py` (or a new module like `generation_vasp.py`).
2. The function must take the same inputs: `Structure`, `CalculationIntent`, `ParameterAdvice`, `SelectionRecord`.
3. Return `tuple[GeneratedFile, ...]`.
4. Add the code name to the `CodeName` literal in `contracts.py`.
5. Wire it into `generate_inputs()` with an `if intent.code == "your_code"` branch.
6. Write tests that prove generated values come from advice/selection records, not from generator-side defaults.

**Rules:**
- Generators must not choose scientific defaults. Every value must come from an advice or selection record.
- Generators must not bypass the pipeline. If you need a value, add it to the advice or selection contract.

## Adding a new calculation task

1. Add the task name to `CalcTask` in `contracts.py`.
2. Extend `generation.py` with task-specific generation logic.
3. Extend the advice stage if the new task needs different default advice.
4. Write tests covering the new task's generation and any changed advice.

**Current limitation:** `CalculationIntent.task` only accepts `"scf_single_point"`. Adding relaxation, band-structure, or DFPT tasks requires advice changes first.

## Adding a new pseudo source

1. Create a new parser function (like `parse_upf_metadata()`) for the new format.
2. Return `PseudoMetadata` instances with the same field contract.
3. Add a new registry loader (like `load_pseudo_metadata()`) if the source has a different directory layout.
4. Selection and ranking logic should work unchanged as long as `PseudoMetadata` fields are populated.

**Rules:**
- Pseudo selection is driven by `PseudoMetadata` fields, not by file paths or formats. Any parser that populates the fields correctly will work with selection.
- Do not add pseudo-type-specific logic to the selection stage. Ranking is generic.

## Adding a new advisor

1. Create a new advisor module under `advisors/`.
2. The advisor should accept a `Structure` and return a typed record (e.g. `KPointSelection`).
3. Wire it into `pipeline.py` or `jobs.py` as needed.
4. Add `ModelSpec` entries if the advisor uses a trained model.

**Rules:**
- Advisors return typed records, not raw values.
- Model-backed advisors should record `provenance.source="model"` and `provenance.data_source` with the model name.

## What not to extend

- **Do not add new job modes** without updating the fixed graph in `jobs.py`. The graph is explicit, not dynamic.
- **Do not bypass stage boundaries.** If Generate needs a value that isn't in the current advice/selection contract, add it to the contract first.
- **Do not add compatibility shims.** One canonical API, one canonical import path.
- **Do not add new external dependencies** unless a stage genuinely cannot exist without one.
- **Do not add Runner/AiiDA/frontend concerns.** Those belong in a separate package.

## Adding new advice categories

1. Define a new advice dataclass in `contracts.py` with `Provenance`.
2. Add it to `ParameterAdvice` as a new field.
3. Add the decision logic to `advice.py`.
4. Add selection logic to `selection.py` if the advice needs concrete resolution.
5. Add generation logic to `generation.py` if the selection produces output that generators need.
6. Update serialization tests.