// Đổi giao diện sáng/tối. Nạp đồng bộ trong <head> để gán data-theme TRƯỚC khi
// trang được vẽ — nạp cuối <body> thì người dùng đang chọn "tối" sẽ thấy một
// lần nháy nền trắng mỗi lần tải trang.
(function () {
  var KEY = '__theme__';
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  // localStorage có thể ném lỗi (chế độ riêng tư, bị chặn lưu trữ).
  function readSaved() {
    try {
      var value = localStorage.getItem(KEY);
      return value === 'dark' || value === 'light' ? value : null;
    } catch (e) {
      return null;
    }
  }

  function save(theme) {
    try {
      localStorage.setItem(KEY, theme);
    } catch (e) { }
  }

  // Chưa chọn tay thì không có data-theme, CSS tự theo hệ điều hành.
  function currentTheme() {
    return root.getAttribute('data-theme') || (media && media.matches ? 'dark' : 'light');
  }

  var saved = readSaved();
  if (saved) root.setAttribute('data-theme', saved);

  function renderButton(button) {
    var isDark = currentTheme() === 'dark';
    // Nút hiển thị chế độ SẼ chuyển sang, không phải chế độ hiện tại.
    button.textContent = isDark ? '☀️' : '🌙';
    button.setAttribute('aria-label', isDark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối');
  }

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('theme_btn');
    if (!button) return;
    renderButton(button);
    var transitionTimer = null;
    button.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      // Bật hiệu ứng mờ dần chỉ trong lúc đổi; bấm liên tục thì gia hạn chứ không gỡ sớm.
      root.classList.add('theme-transition');
      clearTimeout(transitionTimer);
      transitionTimer = setTimeout(function () {
        root.classList.remove('theme-transition');
      }, 400);
      root.setAttribute('data-theme', next);
      save(next);
      renderButton(button);
    });
    // Hệ điều hành đổi theme khi người dùng chưa chọn tay: cập nhật biểu tượng nút.
    if (media && media.addEventListener) {
      media.addEventListener('change', function () { renderButton(button); });
    }
  });
})();
