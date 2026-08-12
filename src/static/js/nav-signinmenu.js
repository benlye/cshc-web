/**
 * Hack to allow the sign-in menu page to work with password manager overlays which take focus.
 * Locks the sign-in page open if focus is in either the username or password field.
 */

(function initSigninMenuLock() {
  const navItem = document.getElementById('nav-signin');
  const trigger = document.getElementById('mega-menu-label-login');
  const menu = document.getElementById('mega-menu-login');
  const form = document.getElementById('signin-menu-form');

  if (!navItem || !trigger || !menu || !form) {
    return;
  }

  const forceOpenMenu = function () {
    navItem.classList.add('login-menu-locked');
    navItem.classList.add('hs-sub-menu-opened');
    navItem.classList.add('u-dropdown-opened');
    trigger.setAttribute('aria-expanded', 'true');
    menu.style.display = 'block';
    menu.style.opacity = '1';
    menu.style.visibility = 'visible';
    menu.style.pointerEvents = 'auto';
  };

  const releaseMenu = function () {
    navItem.classList.remove('login-menu-locked');
    navItem.classList.remove('hs-sub-menu-opened');
    navItem.classList.remove('u-dropdown-opened');
    trigger.setAttribute('aria-expanded', 'false');
    menu.style.removeProperty('display');
    menu.style.removeProperty('opacity');
    menu.style.removeProperty('visibility');
    menu.style.removeProperty('pointer-events');
  };

  form.addEventListener('focusin', function () {
    forceOpenMenu();
  });

  form.addEventListener('focusout', function () {
    setTimeout(function () {
      if (!form.contains(document.activeElement)) {
        releaseMenu();
      } else {
        forceOpenMenu();
      }
    }, 0);
  });

  navItem.addEventListener('mouseleave', function () {
    if (form.contains(document.activeElement)) {
      forceOpenMenu();
    }
  }, true);

  menu.addEventListener('mouseleave', function () {
    if (form.contains(document.activeElement)) {
      forceOpenMenu();
    }
  }, true);
})();