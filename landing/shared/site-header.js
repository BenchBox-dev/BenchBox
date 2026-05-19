(function () {
    function initializeHeader(header) {
        var toggle = header.querySelector("[data-benchbox-site-header-toggle]");
        var nav = header.querySelector("[data-benchbox-site-header-nav]");

        if (!toggle || !nav) {
            return;
        }

        function setOpen(open) {
            header.dataset.menuOpen = open ? "true" : "false";
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
        }

        toggle.addEventListener("click", function () {
            setOpen(toggle.getAttribute("aria-expanded") !== "true");
        });

        nav.addEventListener("click", function (event) {
            if (event.target && event.target.closest("a")) {
                setOpen(false);
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                setOpen(false);
            }
        });
    }

    function updateScrolledState() {
        document.querySelectorAll("[data-benchbox-site-header]").forEach(function (header) {
            header.dataset.scrolled = window.scrollY > 50 ? "true" : "false";
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-benchbox-site-header]").forEach(initializeHeader);
        updateScrolledState();
    });

    window.addEventListener("scroll", updateScrolledState, { passive: true });
})();
