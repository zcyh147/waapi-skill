# Wwise 2022.1 immutable fixture source

This directory is a committed source fixture. Tests must copy it into a per-test sandbox before mutation. Do not set `WWISE_SANDBOX_ROOT` or destructive `WWISE_FIXTURE_PROJECT` to this directory or any descendant.

The fixture was curated from `/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject`. Its fixed `WAAPI Skill Integration V2` business graph was then authored in a disposable copy through the public `waapi-skill` transaction path and promoted back as reviewed `.wwu` files plus the 15 required WAV sources. Tests still copy this committed source into a fresh sandbox before every mutation. Generated Wwise outputs, caches, logs, profiler captures, validation caches, user settings, and runtime sandboxes are intentionally excluded.
