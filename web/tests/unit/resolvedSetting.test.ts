import { describe, expect, it } from "vitest";

import type { ResolvedField, ResolvedIn } from "../../src/api/coreClient";
import {
  resolvedSource,
  resolvedValue,
  settingRecord,
} from "../../src/controls/resolvedSetting";

function setting(key: string, record: string, path: ResolvedIn["path"]) {
  return { key, resolved_in: { record, path } };
}

/** bcc Fe's magnetic record with spin_polarized pinned (#187). */
const magnetic: ResolvedField = {
  status: "resolved",
  value: {
    spin_polarized: true,
    spin_orbit_enabled: false,
    ordering: { requested: null, applied: "fm" },
    tot_magnetization: null,
    moment_direction: null,
  },
  source: "human",
  field_sources: {
    spin_polarized: "human",
    spin_orbit_coupling: "heuristic",
    magnetic_ordering: "heuristic",
  },
};

describe("settingRecord", () => {
  it("reads the record resolved_in names, not the setting's key or group", () => {
    const table = setting("pseudo_table_id", "pseudo_table", ["id"]);
    const record: ResolvedField = { status: "resolved", value: { id: "t" } };

    expect(settingRecord(table, { pseudo_table: record })).toBe(record);
    expect(settingRecord(table, { pseudo_table_id: record })).toBeUndefined();
    expect(settingRecord(table, undefined)).toBeUndefined();
  });
});

describe("resolvedValue", () => {
  it("follows the declared path, not the setting's key", () => {
    expect(
      resolvedValue(
        setting("spin_orbit_coupling", "magnetic", ["spin_orbit_enabled"]),
        magnetic,
      ),
    ).toBe(false);
    expect(
      resolvedValue(
        setting("magnetic_ordering", "magnetic", ["ordering", "applied"]),
        magnetic,
      ),
    ).toBe("fm");
  });

  it("is the record's value itself for an empty path", () => {
    const functional: ResolvedField = { status: "resolved", value: "PBEsol" };

    expect(
      resolvedValue(setting("functional", "functional", []), functional),
    ).toBe("PBEsol");
  });

  it("is nothing without a path, past a null, or for an unresolved record", () => {
    const nbnd: ResolvedField = { status: "resolved", value: { nbnd: 20 } };

    expect(
      resolvedValue(setting("extra_bands", "nbnd", null), nbnd),
    ).toBeUndefined();
    expect(
      resolvedValue(
        setting("moment_direction", "magnetic", ["moment_direction", "uvw"]),
        magnetic,
      ),
    ).toBeUndefined();
    expect(
      resolvedValue(setting("spin_polarized", "magnetic", ["spin_polarized"]), {
        status: "blocked",
        blocked_by: "magnetic",
      }),
    ).toBeUndefined();
  });
});

describe("resolvedSource", () => {
  it("is the setting's own field source", () => {
    expect(
      resolvedSource(
        setting("spin_orbit_coupling", "magnetic", ["spin_orbit_enabled"]),
        magnetic,
      ),
    ).toBe("heuristic");
    expect(
      resolvedSource(
        setting("spin_polarized", "magnetic", ["spin_polarized"]),
        magnetic,
      ),
    ).toBe("human");
  });

  it("is nothing for a setting without a recorded value", () => {
    expect(
      resolvedSource(
        setting("tot_magnetization", "magnetic", ["tot_magnetization"]),
        magnetic,
      ),
    ).toBeUndefined();
    expect(
      resolvedSource(setting("extra_bands", "nbnd", null), {
        status: "resolved",
        value: { nbnd: 20 },
        source: "heuristic",
      }),
    ).toBeUndefined();
  });

  it("falls back to the record's source unless another setting made it human", () => {
    const sampling: ResolvedField = {
      status: "resolved",
      value: { mesh: [4, 4, 4], k_index: 5 },
      source: "ml",
      field_sources: { k_distance: "ml" },
    };
    const cutoffs: ResolvedField = {
      status: "resolved",
      value: { ecutwfc_ry: 60, ecutrho_ry: 240 },
      source: "human",
    };

    expect(
      resolvedSource(setting("k_index", "k_sampling", ["k_index"]), sampling),
    ).toBe("ml");
    expect(
      resolvedSource(setting("ecutrho_ry", "cutoffs", ["ecutrho_ry"]), cutoffs),
    ).toBeUndefined();
  });

  it("is the record's own source, human too, for the record's whole value", () => {
    expect(
      resolvedSource(setting("functional", "functional", []), {
        status: "resolved",
        value: "PBE",
        source: "human",
      }),
    ).toBe("human");
  });
});
