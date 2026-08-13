# Evaluation coverage

- `eval-1` uses `CoreService.recommend()` and the manual Quantum ESPRESSO
  checklist.
- `eval-2` uses `CoreService.generate(..., output_dir=...)` or the
  `goldilocks generate` CLI command.
- `eval-3` checks UPF metadata and cutoff requirements.
- `eval-4` uses the `dft-basics` references for scientific policy choices.
