(function () {
    var storageKey = "benchbox:theme";
    var choices = ["system", "light", "dark"];

    function normalizeChoice(value) {
        return choices.indexOf(value) >= 0 ? value : "system";
    }

    function systemTheme() {
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function storedChoice() {
        try {
            return normalizeChoice(window.localStorage.getItem(storageKey));
        } catch (error) {
            return "system";
        }
    }

    function applyTheme(choice) {
        choice = normalizeChoice(choice);
        var effective = choice === "system" ? systemTheme() : choice;
        document.documentElement.dataset.bbThemeChoice = choice;
        document.documentElement.dataset.bbTheme = effective;
        document.documentElement.dataset.theme = effective;
        document.documentElement.style.colorScheme = effective;
        document.body && document.body.setAttribute("data-theme", effective);

        document.querySelectorAll("[data-benchbox-theme-option]").forEach(function (button) {
            var isSelected = button.getAttribute("data-benchbox-theme-option") === choice;
            button.setAttribute("aria-checked", isSelected ? "true" : "false");
            button.setAttribute("tabindex", isSelected ? "0" : "-1");
        });

        window.dispatchEvent(new CustomEvent("benchbox-theme-change", { detail: { choice: choice, theme: effective } }));
    }

    function setChoice(choice) {
        choice = normalizeChoice(choice);
        try {
            if (choice === "system") {
                window.localStorage.removeItem(storageKey);
            } else {
                window.localStorage.setItem(storageKey, choice);
            }
        } catch (error) {
            // localStorage can be blocked; the data attributes still update for this page.
        }
        applyTheme(choice);
    }

    function initializeToggles() {
        document.querySelectorAll("[data-benchbox-theme-option]").forEach(function (button) {
            button.addEventListener("click", function () {
                setChoice(button.getAttribute("data-benchbox-theme-option"));
            });
        });

        // Roving-tabindex radiogroup per the WAI-ARIA radio pattern: arrow
        // keys move focus and selection together and wrap at the ends;
        // Home/End jump to the first/last option; Space/Enter select.
        document.querySelectorAll('[role="radiogroup"]').forEach(function (group) {
            var options = Array.prototype.slice.call(group.querySelectorAll("[data-benchbox-theme-option]"));
            if (!options.length) return;

            group.addEventListener("keydown", function (event) {
                var currentIndex = options.indexOf(document.activeElement);
                if (currentIndex === -1) return;

                var nextIndex = null;
                switch (event.key) {
                    case "ArrowRight":
                    case "ArrowDown":
                        nextIndex = (currentIndex + 1) % options.length;
                        break;
                    case "ArrowLeft":
                    case "ArrowUp":
                        nextIndex = (currentIndex - 1 + options.length) % options.length;
                        break;
                    case "Home":
                        nextIndex = 0;
                        break;
                    case "End":
                        nextIndex = options.length - 1;
                        break;
                    case " ":
                    case "Spacebar":
                    case "Enter":
                        event.preventDefault();
                        setChoice(options[currentIndex].getAttribute("data-benchbox-theme-option"));
                        return;
                    default:
                        return;
                }

                event.preventDefault();
                var nextButton = options[nextIndex];
                setChoice(nextButton.getAttribute("data-benchbox-theme-option"));
                nextButton.focus();
            });
        });

        applyTheme(storedChoice());
    }

    window.BenchBoxTheme = {
        key: storageKey,
        choices: choices.slice(),
        getChoice: storedChoice,
        setChoice: setChoice,
        applyTheme: applyTheme,
    };

    applyTheme(storedChoice());

    if (window.matchMedia) {
        var media = window.matchMedia("(prefers-color-scheme: dark)");
        var onSystemThemeChange = function () {
            if ((document.documentElement.dataset.bbThemeChoice || storedChoice()) === "system") {
                applyTheme("system");
            }
        };
        if (media.addEventListener) {
            media.addEventListener("change", onSystemThemeChange);
        } else if (media.addListener) {
            media.addListener(onSystemThemeChange);
        }
    }

    document.addEventListener("DOMContentLoaded", initializeToggles);
})();
