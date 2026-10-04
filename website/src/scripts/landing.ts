const copyButtons = [...document.querySelectorAll<HTMLButtonElement>(".landing .copy-btn")];
const sectionLinks = [...document.querySelectorAll<HTMLAnchorElement>('.landing a[href^="#"]')];
const sectionNav = document.querySelector<HTMLElement>(".section-nav");
const sectionNavLinksContainer = document.querySelector<HTMLElement>(".section-nav__links");
const sectionNavLinks = [...document.querySelectorAll<HTMLAnchorElement>(".section-nav__link")];
const sectionNavSections = sectionNavLinks
  .map((link) => document.querySelector<HTMLElement>(link.getAttribute("href") ?? ""))
  .filter((section): section is HTMLElement => section !== null);
let currentSectionId = sectionNavLinks.find((link) => link.hasAttribute("aria-current"))?.getAttribute("href");

function sectionNavigationOffset(): number {
  const siteHeader = document.querySelector("[data-site-header]");
  return (siteHeader?.getBoundingClientRect().height ?? 0) + (sectionNav?.getBoundingClientRect().height ?? 0);
}

function updateCurrentSection(): void {
  if (!sectionNavSections.length) return;
  const marker = sectionNavigationOffset() + 16;
  let currentSection = sectionNavSections[0];
  for (const section of sectionNavSections) {
    if (section.getBoundingClientRect().top <= marker) currentSection = section;
  }
  for (const link of sectionNavLinks) {
    if (link.getAttribute("href") === `#${currentSection.id}`) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
  const nextSectionId = `#${currentSection.id}`;
  if (nextSectionId === currentSectionId) return;
  const currentLink = sectionNavLinks.find((link) => link.getAttribute("href") === nextSectionId);
  if (currentLink && sectionNavLinksContainer) {
    const left = currentLink.offsetLeft - (sectionNavLinksContainer.clientWidth - currentLink.offsetWidth) / 2;
    sectionNavLinksContainer.scrollTo({ left, behavior: "smooth" });
  }
  currentSectionId = nextSectionId;
}

let sectionNavigationFrame: number | null = null;
function scheduleCurrentSectionUpdate(): void {
  if (sectionNavigationFrame !== null) return;
  sectionNavigationFrame = window.requestAnimationFrame(() => {
    sectionNavigationFrame = null;
    updateCurrentSection();
  });
}

window.addEventListener("scroll", scheduleCurrentSectionUpdate, { passive: true });
window.addEventListener("resize", scheduleCurrentSectionUpdate);
window.addEventListener("load", updateCurrentSection);

function copyWithTextarea(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.left = "-999999px";
  area.style.top = "-999999px";
  document.body.appendChild(area);
  area.focus();
  area.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
  }
}

for (const button of copyButtons) {
  button.addEventListener("click", async () => {
    const targetId = button.dataset.target;
    const code = targetId ? document.getElementById(targetId) : button.closest(".code-block")?.querySelector("code");
    const text = code?.textContent?.trim();
    if (!text) return;
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      copied = copyWithTextarea(text);
    }
    if (!copied) return;
    button.textContent = "Copied!";
    button.classList.add("copied");
    window.setTimeout(() => {
      button.textContent = "Copy";
      button.classList.remove("copied");
    }, 2000);
  });
}

for (const link of sectionLinks) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const targetId = link.getAttribute("href") ?? "";
    const target = document.querySelector(targetId);
    if (!target) return;
    if (window.location.hash !== targetId) window.history.pushState(null, "", targetId);
    const top = target.getBoundingClientRect().top + window.pageYOffset - sectionNavigationOffset();
    window.scrollTo({ top, behavior: "smooth" });
    window.setTimeout(updateCurrentSection, 500);
  });
}
