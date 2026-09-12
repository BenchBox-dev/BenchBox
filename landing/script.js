// DOM Elements
const copyButtons = document.querySelectorAll('.copy-btn');
const sectionLinks = document.querySelectorAll('a[href^="#"]');
const sectionNav = document.querySelector('.section-nav');
const sectionNavLinksContainer = document.querySelector('.section-nav__links');
const sectionNavLinks = Array.from(document.querySelectorAll('.section-nav__link'));
const sectionNavSections = sectionNavLinks
    .map(link => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
let currentSectionId = sectionNavLinks.find(link => link.hasAttribute('aria-current'))?.getAttribute('href');

function sectionNavigationOffset() {
    const siteHeader = document.querySelector('.benchbox-site-header');
    return (siteHeader?.getBoundingClientRect().height || 0) + (sectionNav?.getBoundingClientRect().height || 0);
}

function updateCurrentSection() {
    if (!sectionNavSections.length) return;

    const marker = sectionNavigationOffset() + 1;
    let currentSection = sectionNavSections[0];
    sectionNavSections.forEach(section => {
        if (section.getBoundingClientRect().top <= marker) currentSection = section;
    });

    sectionNavLinks.forEach(link => {
        const isCurrent = link.getAttribute('href') === `#${currentSection.id}`;
        if (isCurrent) {
            link.setAttribute('aria-current', 'location');
        } else {
            link.removeAttribute('aria-current');
        }
    });

    const nextSectionId = `#${currentSection.id}`;
    if (nextSectionId !== currentSectionId) {
        const currentLink = sectionNavLinks.find(link => link.getAttribute('href') === nextSectionId);
        if (currentLink && sectionNavLinksContainer) {
            const centeredLeft =
                currentLink.offsetLeft - (sectionNavLinksContainer.clientWidth - currentLink.offsetWidth) / 2;
            sectionNavLinksContainer.scrollTo({ left: centeredLeft, behavior: 'smooth' });
        }
        currentSectionId = nextSectionId;
    }
}

let sectionNavigationFrame;
function scheduleCurrentSectionUpdate() {
    if (sectionNavigationFrame) return;
    sectionNavigationFrame = window.requestAnimationFrame(() => {
        sectionNavigationFrame = null;
        updateCurrentSection();
    });
}

window.addEventListener('scroll', scheduleCurrentSectionUpdate, { passive: true });
window.addEventListener('resize', scheduleCurrentSectionUpdate);
window.addEventListener('load', updateCurrentSection);

// Copy to clipboard functionality
copyButtons.forEach(button => {
    button.addEventListener('click', async () => {
        const targetId = button.getAttribute('data-target');
        const codeElement = targetId ? document.getElementById(targetId) : button.closest('.code-block').querySelector('code');

        if (!codeElement) return;

        const textToCopy = codeElement.textContent.trim();

        try {
            await navigator.clipboard.writeText(textToCopy);

            // Visual feedback
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');

            // Reset after 2 seconds
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);

        } catch (err) {
            // Fallback for older browsers
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

// Smooth scrolling for same-page links
sectionLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();

        const targetId = link.getAttribute('href');
        const targetElement = document.querySelector(targetId);

        if (targetElement) {
            const headerOffset = sectionNavigationOffset();
            const elementPosition = targetElement.getBoundingClientRect().top;
            const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

            window.scrollTo({
                top: offsetPosition,
                behavior: 'smooth'
            });
            window.setTimeout(updateCurrentSection, 500);
        }
    });
});

// Intersection Observer for fade-in animations
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

// Observe elements for animation
document.addEventListener('DOMContentLoaded', () => {
    const animateElements = document.querySelectorAll('.feature-card, .benchmark-card, .install-step');

    animateElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

// Add loading state for code copy operations
function showLoadingState(button) {
    const originalText = button.textContent;
    button.textContent = 'Copying...';
    button.disabled = true;

    return () => {
        button.textContent = originalText;
        button.disabled = false;
    };
}

// Enhanced copy functionality with loading states
copyButtons.forEach(button => {
    const originalClickHandler = button.onclick;
    button.addEventListener('click', async (e) => {
        const resetLoading = showLoadingState(button);

        // Small delay to show loading state
        await new Promise(resolve => setTimeout(resolve, 100));

        resetLoading();
    });
});

// Track analytics events (placeholder for future implementation)
function trackEvent(eventName, properties = {}) {
    // Placeholder for analytics tracking
    console.log('Event:', eventName, properties);
}

// Track copy events
copyButtons.forEach(button => {
    button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-target') || 'code-block';
        trackEvent('code_copied', { target: targetId });
    });
});

// Track same-page navigation clicks
sectionLinks.forEach(link => {
    link.addEventListener('click', () => {
        const section = link.getAttribute('href');
        trackEvent('navigation_click', { section });
    });
});

console.log('BenchBox landing page loaded successfully!');
