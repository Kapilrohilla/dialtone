import { describe, expect, it } from "vitest";
import { useRouter, usePathname } from "next/navigation";
import { route } from "@/test/navigation";
import { renderWithProviders, router } from "@/test/render";

function Probe() {
  const r = useRouter();
  return (
    <button onClick={() => r.push("/agents")}>
      {usePathname()}
    </button>
  );
}

// These two run in order: the second proves the first left nothing behind.
describe("harness isolation", () => {
  it("records a router call and a route", () => {
    const { getByRole } = renderWithProviders(<Probe />, { route: "/calls?page=2" });
    getByRole("button").click();
    expect(router.push).toHaveBeenCalledWith("/agents");
    expect(getByRole("button")).toHaveTextContent("/calls");
  });

  it("starts the next test with a clean router and the default route", () => {
    expect(router.push).not.toHaveBeenCalled();
    expect(route).toEqual({ pathname: "/", search: "" });
  });
});
