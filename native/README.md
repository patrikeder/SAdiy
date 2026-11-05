# native/ (C++ or Rust, only if needed)

Empty on purpose. Move code here only after profiling shows the Python sweep loop is the
bottleneck (expect PLL lock time and ADC read time to dominate first).

Candidate: the inner sweep loop (tune, settle, read, average) as a pybind11 or PyO3 extension
that keeps the same `SweepEngine.run(points, atten_db)` interface. Keep `core/` as the
reference implementation and compare outputs against it in tests.
