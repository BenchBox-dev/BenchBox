(function () {
    var storageKey = "benchbox:theme";
    var choices = ["system", "light", "dark"];

    function systemTheme() {
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function storedChoice() {
        try {
            var value = window.localStorage.getItem(storageKey);
            return choices.indexOf(value) >= 0 ? value : "system";
        } catch (error) {
            return "system";
        }
    }

    function applyTheme(choice) {
        var effective = choice === "system" ? systemTheme() : choice;
        document.documentElement.dataset.bbThemeChoice = choice;
        document.documentElement.dataset.bbTheme = effective;
        document.documentElement.dataset.theme = effective;
        document.documentElement.style.colorScheme = effective;
        document.body && document.body.setAttribute("data-theme", effective);

        document.querySelectorAll("[data-benchbox-theme-toggle]").forEach(function (button) {
            button.setAttribute("aria-label", "Theme: " + choice + ". Activate to switch theme.");
            button.setAttribute("title", "Theme: " + choice);
            button.textContent = choice === "system" ? "System" : choice.charAt(0).toUpperCase() + choice.slice(1);
        });

        window.dispatchEvent(new CustomEvent("benchbox-theme-change", { detail: { choice: choice, theme: effective } }));
    }

    function setChoice(choice) {
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

    function nextChoice(choice) {
        return choices[(choices.indexOf(choice) + 1) % choices.length] || "system";
    }

    function initializeToggles() {
        document.querySelectorAll("[data-benchbox-theme-toggle]").forEach(function (button) {
            button.addEventListener("click", function () {
                setChoice(nextChoice(document.documentElement.dataset.bbThemeChoice || storedChoice()));
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
