import { expect, test } from "@playwright/test";

test("security UI limits demo identities and enforces guest path boundaries", async ({ page }) => {
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  await page.goto("/");
  if (await page.locator("#desktop").isHidden()) await page.locator("#skip-boot").click();
  await expect(page.locator("#desktop")).toBeVisible();
  await expect(page.locator("#connection-label")).toHaveText("Kernel connected");

  await page.getByRole("button", { name: "Open start menu" }).first().click();
  const startMenu = page.getByRole("region", { name: "Start menu" });
  await startMenu.getByRole("button", { name: /Security/ }).click();

  const security = page.getByRole("region", { name: "Security" });
  const account = security.getByLabel("Demo account");
  await expect(account.locator("option")).toHaveCount(2);
  await expect(account.locator("option")).toHaveText([
    "guest · reader",
    "librarian · circulation",
  ]);

  await account.selectOption("librarian");
  await security.getByRole("button", { name: "Switch user" }).click();
  await expect(security.locator("#security-current-user")).toHaveText("librarian");

  await account.selectOption("guest");
  await security.getByRole("button", { name: "Switch user" }).click();
  await expect(security.locator("#security-current-user")).toHaveText("guest");

  const authorizationForm = security.locator("#security-authorize-form");
  await authorizationForm.locator('[name="action"]').selectOption("write");
  await authorizationForm.locator('[name="user"]').fill("guest");
  await authorizationForm.locator('[name="owner"]').fill("guest");
  await authorizationForm.locator('[name="path"]').fill("/home/guest-sibling/notes.txt");
  await authorizationForm.getByRole("button", { name: "Check access" }).click();
  await expect(security.locator("#security-authorization-result")).toHaveText("Access denied.");

  await authorizationForm.locator('[name="path"]').fill("/home/guest/notes.txt");
  await authorizationForm.getByRole("button", { name: "Check access" }).click();
  await expect(security.locator("#security-authorization-result")).toHaveText("Access granted.");

  expect(browserErrors).toEqual([]);
});
