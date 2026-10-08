const copyButtons = document.querySelectorAll('.copy-btn');
const navLinks = document.querySelectorAll('.nav-links a[href^="#"]');

copyButtons.forEach(button => {
    button.addEventListener('click', async () => {
        const targetId = button.getAttribute('data-target');
        const codeElement = targetId ? document.getElementById(targetId) : button.closest('.code-block').querySelector('code');

        if (!codeElement) return;

        const textToCopy = codeElement.textContent.trim();

        try {
            await navigator.clipboard.writeText(textToCopy);

            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');

            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);

        } catch (err) {
            const textArea = document.createElement('textarea');
            textArea.value = textToCopy;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();

            try {
                document.execCommand('copy');
                button.textContent = 'Copied!';
                button.classList.add('copied');

                setTimeout(() => {
                    button.textContent = 'Copy';
                    button.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy text: ', err);
            }

            document.body.removeChild(textArea);
        }
    });
});

navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();

        const targetId = link.getAttribute('href');
        const targetElement = document.querySelector(targetId);

        if (targetElement) {
            const headerOffset = 80;
            const elementPosition = targetElement.getBoundingClientRect().top;
            const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

            window.scrollTo({
                top: offsetPosition,
                behavior: 'smooth'
            });
        }
    });
});

let ticking = false;

function updateNavBackground() {
    const scrolled = window.scrollY;
    const nav = document.querySelector('.nav');

    if (scrolled > 50) {
        nav.style.backgroundColor = 'rgba(13, 17, 23, 0.98)';
    } else {
        nav.style.backgroundColor = 'rgba(13, 17, 23, 0.95)';
    }

    ticking = false;
}

function requestTick() {
    if (!ticking) {
        requestAnimationFrame(updateNavBackground);
        ticking = true;
    }
}

window.addEventListener('scroll', requestTick);

const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

document.addEventListener('DOMContentLoaded', () => {
    const animateElements = document.querySelectorAll('.feature-card, .benchmark-card, .install-step');

    animateElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

function createMobileMenu() {
    const nav = document.querySelector('.nav-container');
    const navLinks = document.querySelector('.nav-links');

    const hamburger = document.createElement('button');
    hamburger.className = 'mobile-menu-toggle';
    hamburger.innerHTML = `
        <span></span>
        <span></span>
        <span></span>
    `;
    hamburger.style.cssText = `
        display: none;
        flex-direction: column;
        background: none;
        border: none;
        cursor: pointer;
        padding: 4px;
    `;

    hamburger.querySelectorAll('span').forEach(span => {
        span.style.cssText = `
            width: 20px;
            height: 2px;
            background-color: var(--text-primary);
            margin: 2px 0;
            transition: 0.3s;
        `;
    });

    nav.insertBefore(hamburger, navLinks);

    hamburger.addEventListener('click', () => {
        navLinks.classList.toggle('mobile-open');
        hamburger.classList.toggle('active');
    });

    const mediaQuery = window.matchMedia('(max-width: 768px)');
    function handleMediaQuery(e) {
        if (e.matches) {
            hamburger.style.display = 'flex';
            navLinks.style.cssText = `
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                background-color: var(--bg-primary);
                border-top: 1px solid var(--border-primary);
                flex-direction: column;
                padding: var(--space-lg);
                transform: translateY(-100%);
                opacity: 0;
                pointer-events: none;
                transition: all 0.3s ease;
            `;
        } else {
            hamburger.style.display = 'none';
            navLinks.style.cssText = '';
            navLinks.classList.remove('mobile-open');
        }
    }

    mediaQuery.addListener(handleMediaQuery);
    handleMediaQuery(mediaQuery);

    const style = document.createElement('style');
    style.textContent = `
        .nav-links.mobile-open {
            transform: translateY(0) !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }

        .mobile-menu-toggle.active span:nth-child(1) {
            transform: rotate(-45deg) translate(-5px, 5px);
        }

        .mobile-menu-toggle.active span:nth-child(2) {
            opacity: 0;
        }

        .mobile-menu-toggle.active span:nth-child(3) {
            transform: rotate(45deg) translate(-5px, -5px);
        }
    `;
    document.head.appendChild(style);
}

document.addEventListener('DOMContentLoaded', createMobileMenu);

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const navLinks = document.querySelector('.nav-links');
        const hamburger = document.querySelector('.mobile-menu-toggle');
        if (navLinks && navLinks.classList.contains('mobile-open')) {
            navLinks.classList.remove('mobile-open');
            hamburger.classList.remove('active');
        }
    }
});

let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        const navLinks = document.querySelector('.nav-links');
        if (window.innerWidth > 768 && navLinks.classList.contains('mobile-open')) {
            navLinks.classList.remove('mobile-open');
            document.querySelector('.mobile-menu-toggle').classList.remove('active');
        }
    }, 250);
});

function showLoadingState(button) {
    const originalText = button.textContent;
    button.textContent = 'Copying...';
    button.disabled = true;

    return () => {
        button.textContent = originalText;
        button.disabled = false;
    };
}

copyButtons.forEach(button => {
    const originalClickHandler = button.onclick;
    button.addEventListener('click', async (e) => {
        const resetLoading = showLoadingState(button);

        await new Promise(resolve => setTimeout(resolve, 100));

        resetLoading();
    });
});

function trackEvent(eventName, properties = {}) {
    console.log('Event:', eventName, properties);
}

copyButtons.forEach(button => {
    button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-target') || 'code-block';
        trackEvent('code_copied', { target: targetId });
    });
});

navLinks.forEach(link => {
    link.addEventListener('click', () => {
        const section = link.getAttribute('href');
        trackEvent('navigation_click', { section });
    });
});

console.log('BenchBox landing page loaded successfully!');
