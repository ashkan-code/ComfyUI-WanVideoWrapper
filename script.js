// ===== Navbar Scroll Effect =====
const navbar = document.getElementById('navbar');
const navLinks = document.querySelectorAll('.nav-link');

window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
        navbar.classList.add('scrolled');
    } else {
        navbar.classList.remove('scrolled');
    }
});

// ===== Mobile Menu Toggle =====
const hamburger = document.getElementById('hamburger');
const navMenu = document.getElementById('navMenu');

hamburger.addEventListener('click', () => {
    navMenu.classList.toggle('active');

    // Animate hamburger icon
    const spans = hamburger.querySelectorAll('span');
    if (navMenu.classList.contains('active')) {
        spans[0].style.transform = 'rotate(45deg) translate(7px, 7px)';
        spans[1].style.opacity = '0';
        spans[2].style.transform = 'rotate(-45deg) translate(7px, -7px)';
    } else {
        spans[0].style.transform = 'none';
        spans[1].style.opacity = '1';
        spans[2].style.transform = 'none';
    }
});

// Close mobile menu when clicking on a link
navLinks.forEach(link => {
    link.addEventListener('click', () => {
        navMenu.classList.remove('active');
        const spans = hamburger.querySelectorAll('span');
        spans[0].style.transform = 'none';
        spans[1].style.opacity = '1';
        spans[2].style.transform = 'none';
    });
});

// ===== Smooth Scroll with Offset =====
navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const targetId = link.getAttribute('href');
        const targetSection = document.querySelector(targetId);

        if (targetSection) {
            const offsetTop = targetSection.offsetTop - 80;
            window.scrollTo({
                top: offsetTop,
                behavior: 'smooth'
            });
        }
    });
});

// ===== Menu Tab Switching =====
const menuTabs = document.querySelectorAll('.menu-tab');
const menuCategories = document.querySelectorAll('.menu-category');

menuTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        // Remove active class from all tabs and categories
        menuTabs.forEach(t => t.classList.remove('active'));
        menuCategories.forEach(c => c.classList.remove('active'));

        // Add active class to clicked tab
        tab.classList.add('active');

        // Show corresponding category
        const category = tab.getAttribute('data-category');
        const targetCategory = document.getElementById(category);
        if (targetCategory) {
            targetCategory.classList.add('active');
        }
    });
});

// ===== Reservation Form Validation & Submission =====
const reservationForm = document.getElementById('reservationForm');

if (reservationForm) {
    // Set minimum date to today
    const dateInput = document.getElementById('date');
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const minDate = tomorrow.toISOString().split('T')[0];
    dateInput.setAttribute('min', minDate);

    reservationForm.addEventListener('submit', (e) => {
        e.preventDefault();

        // Get form values
        const formData = {
            name: document.getElementById('name').value,
            email: document.getElementById('email').value,
            phone: document.getElementById('phone').value,
            guests: document.getElementById('guests').value,
            date: document.getElementById('date').value,
            time: document.getElementById('time').value,
            message: document.getElementById('message').value
        };

        // Validate form
        if (!formData.name || !formData.email || !formData.phone ||
            !formData.guests || !formData.date || !formData.time) {
            alert('Please fill in all required fields.');
            return;
        }

        // Email validation
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(formData.email)) {
            alert('Please enter a valid email address.');
            return;
        }

        // Phone validation (basic)
        const phoneRegex = /^[\d\s\-\+\(\)]+$/;
        if (!phoneRegex.test(formData.phone)) {
            alert('Please enter a valid phone number.');
            return;
        }

        // Success message
        alert(`Thank you, ${formData.name}! Your reservation for ${formData.guests} guest(s) on ${formData.date} at ${formData.time} has been received. We'll send a confirmation to ${formData.email} shortly.`);

        // Reset form
        reservationForm.reset();

        // In a real application, you would send this data to a server
        console.log('Reservation Data:', formData);
    });
}

// ===== Contact Form Validation & Submission =====
const contactForm = document.getElementById('contactForm');

if (contactForm) {
    contactForm.addEventListener('submit', (e) => {
        e.preventDefault();

        // Get form values
        const formData = {
            name: document.getElementById('contact-name').value,
            email: document.getElementById('contact-email').value,
            subject: document.getElementById('subject').value,
            message: document.getElementById('contact-message').value
        };

        // Validate form
        if (!formData.name || !formData.email || !formData.subject || !formData.message) {
            alert('Please fill in all fields.');
            return;
        }

        // Email validation
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(formData.email)) {
            alert('Please enter a valid email address.');
            return;
        }

        // Success message
        alert(`Thank you, ${formData.name}! Your message has been sent. We'll respond to ${formData.email} as soon as possible.`);

        // Reset form
        contactForm.reset();

        // In a real application, you would send this data to a server
        console.log('Contact Form Data:', formData);
    });
}

// ===== Scroll Reveal Animation =====
const revealElements = document.querySelectorAll('.menu-item, .gallery-item, .feature, .contact-item');

const revealOnScroll = () => {
    const windowHeight = window.innerHeight;

    revealElements.forEach(element => {
        const elementTop = element.getBoundingClientRect().top;
        const revealPoint = 150;

        if (elementTop < windowHeight - revealPoint) {
            element.style.opacity = '1';
            element.style.transform = 'translateY(0)';
        }
    });
};

// Initialize elements for reveal animation
revealElements.forEach(element => {
    element.style.opacity = '0';
    element.style.transform = 'translateY(30px)';
    element.style.transition = 'all 0.6s ease';
});

window.addEventListener('scroll', revealOnScroll);
window.addEventListener('load', revealOnScroll);

// ===== Active Nav Link on Scroll =====
const sections = document.querySelectorAll('section[id]');

const highlightNav = () => {
    const scrollY = window.pageYOffset;

    sections.forEach(section => {
        const sectionHeight = section.offsetHeight;
        const sectionTop = section.offsetTop - 100;
        const sectionId = section.getAttribute('id');

        if (scrollY > sectionTop && scrollY <= sectionTop + sectionHeight) {
            navLinks.forEach(link => {
                link.classList.remove('active');
                if (link.getAttribute('href') === `#${sectionId}`) {
                    link.classList.add('active');
                }
            });
        }
    });
};

window.addEventListener('scroll', highlightNav);

// ===== Gallery Item Hover Effect =====
const galleryItems = document.querySelectorAll('.gallery-item');

galleryItems.forEach(item => {
    item.addEventListener('mouseenter', function() {
        this.style.transform = 'scale(1.05)';
        this.style.zIndex = '10';
    });

    item.addEventListener('mouseleave', function() {
        this.style.transform = 'scale(1)';
        this.style.zIndex = '1';
    });
});

// ===== Counter Animation for About Features (Optional Enhancement) =====
let countersAnimated = false;

const animateCounters = () => {
    if (countersAnimated) return;

    const aboutSection = document.getElementById('about');
    const aboutTop = aboutSection.offsetTop;
    const aboutHeight = aboutSection.offsetHeight;
    const scrollPosition = window.scrollY + window.innerHeight;

    if (scrollPosition > aboutTop && window.scrollY < aboutTop + aboutHeight) {
        countersAnimated = true;

        // Add any counter animations here if needed
        const features = document.querySelectorAll('.feature');
        features.forEach((feature, index) => {
            setTimeout(() => {
                feature.style.opacity = '1';
                feature.style.transform = 'translateY(0) scale(1)';
            }, index * 150);
        });
    }
};

window.addEventListener('scroll', animateCounters);

// ===== Parallax Effect for Hero Section (Subtle) =====
const hero = document.querySelector('.hero');

window.addEventListener('scroll', () => {
    const scrolled = window.pageYOffset;
    const parallax = scrolled * 0.5;

    if (hero) {
        hero.style.transform = `translateY(${parallax}px)`;
    }
});

// ===== Initialize Page =====
document.addEventListener('DOMContentLoaded', () => {
    // Trigger initial animations
    revealOnScroll();
    highlightNav();

    // Add smooth transition to body
    document.body.style.opacity = '0';
    setTimeout(() => {
        document.body.style.transition = 'opacity 0.5s ease';
        document.body.style.opacity = '1';
    }, 100);

    console.log('Savoria Restaurant Website Loaded Successfully!');
});

// ===== Performance Optimization =====
// Debounce scroll events for better performance
let scrollTimeout;
window.addEventListener('scroll', () => {
    if (scrollTimeout) {
        window.cancelAnimationFrame(scrollTimeout);
    }

    scrollTimeout = window.requestAnimationFrame(() => {
        // Scroll-dependent functions are already attached
    });
});

// ===== Accessibility Enhancements =====
// Add keyboard navigation support
document.addEventListener('keydown', (e) => {
    // Close mobile menu on Escape key
    if (e.key === 'Escape' && navMenu.classList.contains('active')) {
        navMenu.classList.remove('active');
        const spans = hamburger.querySelectorAll('span');
        spans[0].style.transform = 'none';
        spans[1].style.opacity = '1';
        spans[2].style.transform = 'none';
    }
});

// Focus trap for mobile menu
const focusableElements = navMenu.querySelectorAll('a, button');
const firstFocusable = focusableElements[0];
const lastFocusable = focusableElements[focusableElements.length - 1];

navMenu.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        if (e.shiftKey) {
            if (document.activeElement === firstFocusable) {
                e.preventDefault();
                lastFocusable.focus();
            }
        } else {
            if (document.activeElement === lastFocusable) {
                e.preventDefault();
                firstFocusable.focus();
            }
        }
    }
});
