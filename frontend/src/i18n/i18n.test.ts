import { describe, expect, it } from "vitest";
import en from "./en";
import nl from "./nl";
import { translate } from "./index";

describe("i18n", () => {
  it("has identical key sets for en and nl", () => {
    expect(Object.keys(nl).sort()).toEqual(Object.keys(en).sort());
  });
  it("has no empty translations", () => {
    for (const v of Object.values(nl)) expect(v.trim()).not.toBe("");
  });
  it("translates", () => {
    expect(translate("nl", "nav.employees")).toBe("Medewerkers");
    expect(translate("en", "nav.employees")).toBe("Employees");
  });
});
