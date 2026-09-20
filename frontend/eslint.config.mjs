import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

// Next 16 removed the built-in `next lint` command and eslint-config-next
// ships flat-config-ready arrays directly (no FlatCompat shim needed) —
// see the "lint" script in package.json, which now calls `eslint` directly.
export default [
  { ignores: [".next/**", "node_modules/**"] },
  ...nextCoreWebVitals,
  {
    // The data-fetching hooks (useReport/useResearchList/useResearchStatus)
    // load on mount and poll on an interval, guarded by a mounted-ref and a
    // cleanup function — the standard "synchronize with an external system"
    // effect pattern React's own docs endorse. The new (React Compiler-era)
    // react-hooks/set-state-in-effect rule flags this categorically; fixing
    // it "properly" means adopting a data-fetching library or `use()` across
    // every hook, which is a real architecture change out of scope for a
    // dependency-upgrade CI fix. Kept as a warning, not silenced entirely.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];
