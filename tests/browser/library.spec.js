import { expect, test } from "@playwright/test";

test("library search is available to guests and circulation is librarian-only", async ({ page }) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.goto("/");
  if (await page.locator("#desktop").isHidden()) await page.locator("#skip-boot").click();
  await expect(page.locator("#desktop")).toBeVisible();
  await expect(page.locator("#connection-label")).toHaveText("Kernel connected");

  const openAppFromMenu = async (name) => {
    await page.getByRole("button", { name: "Open start menu" }).first().click();
    const startMenu = page.getByRole("region", { name: "Start menu" });
    await startMenu.getByRole("button", { name: new RegExp(name) }).click();
  };

  await openAppFromMenu("Library");
  const library = page.getByRole("region", { name: "Library" });
  await expect(library.locator("[data-library-status]")).toHaveText("Signed in as guest.");

  await library.getByRole("textbox", { name: "Search books" }).fill("B013");
  await library.getByRole("button", { name: "Search" }).click();
  const book = library.locator("[data-library-books] article").filter({ hasText: "B013" });
  await expect(book).toHaveCount(1);
  await library.locator("[data-library-member]").selectOption("M025");
  await book.getByRole("button", { name: "Check out" }).click();
  await expect(library.locator("[data-library-status]")).toContainText(
    "user guest is not allowed to write /issued",
  );

  await openAppFromMenu("Security");
  const security = page.getByRole("region", { name: "Security" });
  await security.getByLabel("Demo account").selectOption("librarian");
  await security.getByRole("button", { name: "Switch user" }).click();
  await expect(security.locator("#security-current-user")).toHaveText("librarian");

  await openAppFromMenu("Library");
  await expect(library.locator("[data-library-status]")).toHaveText("Signed in as librarian.");
  await library.getByRole("textbox", { name: "Search books" }).fill("B013");
  await library.getByRole("button", { name: "Search" }).click();
  await expect(book).toHaveCount(1);
  await library.locator("[data-library-member]").selectOption("M025");
  const loans = library.locator("[data-library-loans]");
  const initialLoanCount = await loans.locator(":scope > div").count();
  await book.getByRole("button", { name: "Check out" }).click();
  await expect(loans.locator(":scope > div")).toHaveCount(initialLoanCount + 1);

  expect(browserErrors).toEqual([]);
});
