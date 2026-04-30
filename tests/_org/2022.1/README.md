# Wwise 2022.1 immutable fixture source

This directory is a committed source fixture. Tests must copy it into a per-test sandbox before mutation. Do not set `WWISE_SANDBOX_ROOT` or destructive `WWISE_FIXTURE_PROJECT` to this directory or any descendant.

The fixture was curated from `/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject`: all `.wproj`/`.wwu` authored source files are included, plus a tiny `Originals/**/*.wav` subset for deterministic media/LFS coverage. Generated Wwise outputs, caches, logs, profiler captures, validation caches, user settings, and runtime sandboxes are intentionally excluded.
