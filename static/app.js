'use strict';

const PREFETCH_SIZE = 3;
const TICK_MS = 500;
// Đoạn dài hơn ngần này từ thì nút "Xuống dòng" mới cắt.
const MAX_TU_MOI_DONG = 30;

const STORAGE = {
  queue: '__queue_texts__',
  items: '__base64_items__',
};

// Lỗi tạm thời thì thử lại; lỗi do chính nội dung (413, 422) thì thử lại
// bao nhiêu lần cũng hỏng y như vậy, phải bỏ câu đó đi kẻo lặp vô hạn.
const coTheThuLai = (status) => !status || status === 429 || status >= 500;

const postJson = async (url, body) => {
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw Object.assign(new Error('Không kết nối được máy chủ, sẽ thử lại.'), { retryAfter: 5 });
  }

  if (!res.ok) {
    let detail = 'Máy chủ trả lỗi ' + res.status + '.';
    try {
      const data = await res.json();
      if (data && data.detail) detail = data.detail;
    } catch (e) {
      // Thân phản hồi không phải JSON, giữ thông báo mặc định.
    }
    const retryAfter = parseInt(res.headers.get('Retry-After') || '', 10);
    throw Object.assign(new Error(detail), {
      status: res.status,
      retryAfter: isFinite(retryAfter) ? retryAfter : 5,
    });
  }

  return res.json();
};

/* ---------- Tự động xuống dòng ----------
   Dùng match() thay vì split() với lookbehind: Safari dưới 16.4 không hỗ trợ
   lookbehind và sẽ ném SyntaxError lúc phân tích, làm chết cả file script. */

const demTu = (s) => (s.trim().match(/\S+/g) || []).length;

const tachTheo = (s, re) => (s.match(re) || [s]).map((p) => p.trim()).filter(Boolean);

const ngatCung = (s, gioiHan) => {
  const tu = (s.match(/\S+/g) || []);
  const ra = [];
  for (let i = 0; i < tu.length; i += gioiHan) ra.push(tu.slice(i, i + gioiHan).join(' '));
  return ra;
};

const gomThanhDong = (manh, gioiHan) => {
  const dong = [];
  let hienTai = [];
  let soTu = 0;
  for (const m of manh) {
    const n = demTu(m);
    if (soTu > 0 && soTu + n > gioiHan) {
      dong.push(hienTai.join(' '));
      hienTai = [];
      soTu = 0;
    }
    hienTai.push(m);
    soTu += n;
  }
  if (hienTai.length) dong.push(hienTai.join(' '));
  return dong;
};

const tuDongXuongDong = (text, gioiHan) => {
  gioiHan = gioiHan || MAX_TU_MOI_DONG;
  return text
    .split('\n')
    .map((doan) => {
      if (!doan.trim()) return '';
      // Đủ ngắn thì để nguyên — không cần mỗi câu một dòng.
      if (demTu(doan) <= gioiHan) return doan.trim();

      const manh = [];
      for (const cau of tachTheo(doan, /[^.!?…]+[.!?…]*\s*/g)) {
        if (demTu(cau) <= gioiHan) {
          manh.push(cau);
          continue;
        }
        // Câu tự nó đã quá dài: cắt tiếp ở dấu phẩy, rồi mới cắt cứng theo từ.
        for (const cum of tachTheo(cau, /[^,;:]+[,;:]*\s*/g)) {
          if (demTu(cum) <= gioiHan) manh.push(cum);
          else manh.push(...ngatCung(cum, gioiHan));
        }
      }
      return gomThanhDong(manh, gioiHan).join('\n');
    })
    .join('\n');
};

/* ---------- Hàng đợi đọc ---------- */

const RunAudio = function (params) {
  this.queue_texts = [];
  this.base64_items = [];
  this.media = null;
  this.loading = false;
  this.loading_text = null;
  this.backoff_until = 0;
  this.outputEl = params.outputEl;
  this.queueEl = params.queueEl;
  this.statusEl = params.statusEl;
  this.playPauseEl = params.playPauseEl;

  this.run = () => {
    this.add_event_play_pause(params.playPauseEl);
    this.add_event_next(params.nextEl);
    this.add_event_remove_all(params.removeAllEl);
    this.load_base64_items();
    this.load_queue_texts();
    setInterval(this.tick, TICK_MS);
  };

  this.tick = () => {
    this.prefetch();
    this.play_next();
  };

  this.prefetch = () => {
    if (this.loading) return;
    if (this.base64_items.length >= PREFETCH_SIZE) return;
    if (Date.now() < this.backoff_until) return;
    if (!this.has()) return;

    const text = this.shift_queue();
    if (!text || !text.match(/[a-zA-Z0-9]+/)) return;

    this.loading = true;
    this.loading_text = text;
    this.render_base64_items();
    // Lưu kèm câu đang xử lý: đóng tab giữa chừng thì không mất nội dung.
    this.save_queue_texts(text);

    this.text_to_speech(text)
      .then((res) => {
        // Giữ TEXT GỐC để hiển thị. Chuẩn hoá chỉ phục vụ việc đọc, người dùng
        // không cần thấy phiên bản đã bị cắt câu.
        this.base64_items.push({ text: text, base64: res.base64, name: res.name });
        this.save_base64_items();
        this.save_queue_texts();
        this.set_status('');
      })
      .catch((err) => {
        console.error(err);
        if (coTheThuLai(err.status)) {
          // Trả câu về đầu hàng đợi. Mất mạng hay bị giới hạn tốc độ không
          // được phép nuốt mất nội dung người dùng đã nhập.
          this.queue_texts.unshift(text);
          this.render_queue();
          this.backoff_until = Date.now() + (err.retryAfter || 5) * 1000;
        }
        this.save_queue_texts();
        this.set_status(err.message);
      })
      .finally(() => {
        // Bản cũ quên đặt lại cờ này ở nhánh lỗi, nên một lần hỏng là hàng
        // đợi kẹt cứng vĩnh viễn.
        this.loading = false;
        this.loading_text = null;
        this.render_base64_items();
      });
  };

  this.play_next = () => {
    if (this.media) return;
    if (this.base64_items.length === 0) return;

    const item = this.base64_items[0];
    const media = new Audio('data:audio/mpeg;base64,' + item.base64);
    media.onplay = () => {
      this.playPauseEl.classList.remove('play');
      this.playPauseEl.classList.add('pause');
    };
    media.onpause = () => {
      this.playPauseEl.classList.remove('pause');
      this.playPauseEl.classList.add('play');
    };
    media.onended = () => {
      this.base64_items.shift();
      this.render_base64_items();
      this.save_base64_items();
      this.media = null;
    };
    media.onerror = () => {
      console.error('Không phát được audio, bỏ qua câu này.');
      this.base64_items.shift();
      this.render_base64_items();
      this.save_base64_items();
      this.media = null;
    };
    this.media = media;
    media.play().catch((e) => {
      // Trình duyệt chặn tự phát khi người dùng chưa tương tác với trang.
      console.error(e);
      this.set_status('Bấm nút phát để bắt đầu.');
    });
  };

  this.set_status = (message) => {
    if (this.statusEl) this.statusEl.textContent = message || '';
  };

  this.escape_html = (text) => {
    const div = document.createElement('div');
    div.textContent = typeof text === 'string' ? text.trim() : '';
    return div.innerHTML;
  };

  this.render_queue = () => {
    if (!this.queueEl) return;
    this.queueEl.innerHTML = this.queue_texts
      .map((text) => '<p>' + this.escape_html(text) + '</p>')
      .join('');
  };

  this.render_base64_items = () => {
    if (!this.outputEl) return;
    const parts = this.base64_items.map(
      (item) => '<p>' + this.escape_html(item.text) + '</p>'
    );
    if (this.loading_text) {
      parts.push('<p class="dang-tai">' + this.escape_html(this.loading_text) + '</p>');
    }
    this.outputEl.innerHTML = parts.join('');
  };

  this.add = (text) => {
    this.queue_texts.push(text);
    this.render_queue();
    this.save_queue_texts();
  };

  this.has = () => this.queue_texts.length > 0;

  this.shift_queue = () => {
    const text = this.queue_texts.shift();
    this.render_queue();
    this.save_queue_texts();
    return text;
  };

  this.save_queue_texts = (text) => {
    const queue = (text ? [text] : []).concat(this.queue_texts);
    try {
      window.localStorage.setItem(STORAGE.queue, JSON.stringify(queue));
    } catch (e) {
      console.error(e);
    }
  };

  this.load_queue_texts = () => {
    try {
      const queue = JSON.parse(window.localStorage.getItem(STORAGE.queue));
      if (Array.isArray(queue)) {
        this.queue_texts = queue;
        this.render_queue();
      }
    } catch (e) {
      console.error(e);
    }
  };

  this.save_base64_items = () => {
    try {
      window.localStorage.setItem(STORAGE.items, JSON.stringify(this.base64_items));
    } catch (e) {
      // Hết dung lượng localStorage: bỏ qua, hàng đợi trong bộ nhớ vẫn chạy.
      console.error(e);
    }
  };

  this.load_base64_items = () => {
    try {
      const items = JSON.parse(window.localStorage.getItem(STORAGE.items));
      if (Array.isArray(items)) {
        this.base64_items = items;
        this.render_base64_items();
      }
    } catch (e) {
      console.error(e);
    }
  };

  this.text_to_speech = (text) => postJson('/api/tts', { text: text });

  this.toggle_play_pause = () => {
    if (!this.media) return;
    if (this.media.paused) {
      this.media.play().catch((e) => console.error(e));
    } else {
      this.media.pause();
    }
  };

  this.add_event_play_pause = (ele) => {
    ele.addEventListener('click', this.toggle_play_pause);
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName !== 'TEXTAREA' && e.code === 'Space') {
        e.preventDefault();
        this.toggle_play_pause();
      }
    });
  };

  this.add_event_next = (ele) => {
    ele.addEventListener('click', () => {
      if (!this.media) return;
      this.media.currentTime = this.media.duration;
      if (this.media.paused) this.media.play().catch((e) => console.error(e));
    });
  };

  this.add_event_remove_all = (ele) => {
    ele.addEventListener('click', () => {
      if (this.media && !this.media.paused) this.media.pause();
      this.media = null;
      this.queue_texts = [];
      this.base64_items = [];
      this.backoff_until = 0;
      this.save_base64_items();
      this.save_queue_texts();
      this.render_base64_items();
      this.render_queue();
      this.set_status('');
    });
  };
};

const runAudio = new RunAudio({
  playPauseEl: document.getElementById('playPause'),
  nextEl: document.getElementById('next'),
  removeAllEl: document.getElementById('remove_all'),
  outputEl: document.getElementById('output'),
  queueEl: document.getElementById('queue'),
  statusEl: document.getElementById('status'),
});
runAudio.run();

const processText = (text) => {
  text
    .split('\n')
    .filter((block) => typeof block === 'string' && block.trim())
    .forEach((block) => runAudio.add(block));
};

const readTextFile = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(reader.error);
  reader.readAsText(file);
});

document.getElementById('text_file').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  for (const file of files) {
    try {
      processText(await readTextFile(file));
    } catch (err) {
      console.error(err);
    }
  }
});

const textareaEl = document.getElementById('text_textarea');
const textareaBtnEl = document.getElementById('text_textarea_btn');
const wrapBtnEl = document.getElementById('wrap_btn');

const capNhatNut = () => {
  const rong = !textareaEl.value.trim();
  textareaBtnEl.disabled = rong;
  wrapBtnEl.disabled = rong;
};

textareaEl.addEventListener('input', capNhatNut);

wrapBtnEl.addEventListener('click', () => {
  // Sửa thẳng trong ô nhập để người dùng xem lại và chỉnh trước khi thêm.
  textareaEl.value = tuDongXuongDong(textareaEl.value);
  textareaEl.focus();
  capNhatNut();
});

textareaBtnEl.addEventListener('click', () => {
  processText(textareaEl.value);
  textareaEl.value = '';
  capNhatNut();
});

// Phơi ra để kiểm thử tự động.
window.tuDongXuongDong = tuDongXuongDong;
