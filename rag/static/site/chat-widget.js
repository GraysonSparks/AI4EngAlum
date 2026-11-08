/* Auburn Engineering Giving Assistant — drop-in chat widget.
 *
 * Add to any page with one tag:
 *   <script src="http://<backend-host>/chat-widget.js" defer></script>
 *
 * The widget posts to /chat on the same server it was loaded from (override with
 * data-endpoint="https://.../chat" on the script tag). All styles are scoped under
 * #aug-chat so they can't clash with the host page's CSS.
 *
 * The chat button sits bottom-left, on the same line as the giving site's "back to top" button
 * (bottom-right, 42x38 px, 36 px from the bottom, so its center is 55 px up). Change TOP_BUTTON_MID
 * if the site moves that button.
 *
 * Privacy: the conversation lives only in this page's memory. It is never written to
 * localStorage, sessionStorage, or cookies, and it is gone on reload, navigation, tab close, or
 * "Clear". Recent turns are sent with each request so the assistant can follow up; the server
 * uses them for that answer and does not store them.
 *
 * The widget labels itself as AI in the header, greeting and reply labels. When the assistant can't
 * answer, it gives Ed Collari's contact details first, then his card's "Ask Ed to contact me"
 * button as the second option, instead of a dead end.
 *
 * Those unanswered questions (only the question text, already signed by /chat) are kept in page
 * memory and sent to /unanswered once the visitor is done: when they close or clear the chat,
 * leave the page, or go 10 minutes without asking anything. The server emails them to Advancement
 * and stores nothing.
 *
 * The one thing a visitor can choose to send for storage is the follow-up form (name, email,
 * optional phone and message), posted to /contact only when they tick the consent box and submit.
 * The conversation is not attached to it.
 */
(function () {
  const script = document.currentScript;
  const ENDPOINT = (script && script.dataset.endpoint) ||
    new URL('/chat', script ? script.src : location.href).href;
  const CONTACT_ENDPOINT = (script && script.dataset.contactEndpoint) || new URL('contact', ENDPOINT).href;
  const UNANSWERED_ENDPOINT = (script && script.dataset.unansweredEndpoint) || new URL('unanswered', ENDPOINT).href;
  const MAIN_CONTACT = 'Ed Collari, Executive Director of Development, at elc0042@auburn.edu or 334.844.1488';
  const FALLBACK_REPLY = "I'm having trouble reaching the assistant right now. For help, please contact " + MAIN_CONTACT + '.';
  const IDLE_REPORT_MS = 10 * 60 * 1000; // send unanswered questions after this long without a new one
  const TEASER_KEY = 'aug-chat-teaser-dismissed'; // the only thing stored: a yes/no UI flag
  const HISTORY_SENT = 6; // most recent messages sent with each request
  const TOP_BUTTON_MID = 55; // px from the viewport bottom to the center of the site's back-to-top button

  const css = `
  #aug-chat{--toggle:72px;--navy:#0b2341;--navy-deep:#071830;--orange:#cc4e0b;--orange-hi:#e86100;
    font-family:'Source Sans 3',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.5;}
  #aug-chat *{box-sizing:border-box;}
  #aug-chat .launcher{position:fixed;left:22px;bottom:calc(${TOP_BUTTON_MID}px - var(--toggle) / 2);z-index:2147483000;display:flex;
    flex-direction:row-reverse;align-items:flex-end;gap:12px;}
  #aug-chat .teaser{background:#fff;color:#1d232c;max-width:250px;padding:14px 34px 14px 16px;border-radius:14px;
    box-shadow:0 10px 30px rgba(11,35,65,.22);font-size:15px;line-height:1.4;position:relative;cursor:pointer;
    opacity:0;transform:translateY(8px) scale(.97);transition:opacity .35s ease,transform .35s ease;pointer-events:none;}
  #aug-chat .teaser.show{opacity:1;transform:none;pointer-events:auto;}
  #aug-chat .teaser::after{content:"";position:absolute;left:26px;bottom:-7px;width:14px;height:14px;background:#fff;transform:rotate(45deg);}
  #aug-chat .teaser-close{position:absolute;top:6px;right:8px;border:none;background:none;color:#8a93a0;font-size:16px;line-height:1;cursor:pointer;padding:4px;}
  #aug-chat .teaser-close:hover{color:#1d232c;}
  #aug-chat .toggle{width:var(--toggle);height:var(--toggle);border-radius:50%;background:var(--orange);border:none;cursor:pointer;flex:none;
    box-shadow:0 10px 26px rgba(204,78,11,.42);display:flex;align-items:center;justify-content:center;position:relative;
    transition:transform .15s ease,background .15s ease;}
  #aug-chat .toggle:hover{background:var(--orange-hi);transform:translateY(-2px);}
  #aug-chat .toggle svg{width:34px;height:34px;}
  #aug-chat .ping{position:absolute;top:0;right:0;width:16px;height:16px;border-radius:50%;background:#2bb673;border:2px solid #fff;}
  #aug-chat .panel{position:fixed;left:22px;bottom:26px;width:380px;max-width:calc(100vw - 32px);height:560px;
    max-height:calc(100vh - 52px);min-width:300px;min-height:340px;background:var(--navy-deep);border-radius:16px;
    box-shadow:0 24px 60px rgba(0,0,0,.35);z-index:2147483001;display:flex;flex-direction:column;overflow:hidden;
    transform:translateY(24px) scale(.96);opacity:0;pointer-events:none;transition:opacity .25s ease,transform .25s ease;}
  #aug-chat .panel.open{opacity:1;transform:none;pointer-events:auto;}
  #aug-chat .panel.resizing{transition:none;}
  #aug-chat .resize{position:absolute;right:6px;top:6px;width:16px;height:16px;cursor:nesw-resize;z-index:5;opacity:.55;}
  #aug-chat .resize svg{width:100%;height:100%;stroke:#8aa0c4;stroke-width:1.5;}
  #aug-chat .resize:hover{opacity:.9;}
  #aug-chat .head{padding:18px 18px 16px;display:flex;align-items:center;gap:12px;
    background:linear-gradient(135deg,#153a66 0%,var(--navy) 60%);border-bottom:1px solid rgba(255,255,255,.08);}
  #aug-chat .avatar{width:38px;height:38px;border-radius:50%;background:var(--orange);display:flex;align-items:center;justify-content:center;flex:none;}
  #aug-chat .avatar svg{width:20px;height:20px;stroke:#fff;fill:none;stroke-width:2;}
  #aug-chat .head-text{flex:1;min-width:0;}
  #aug-chat .name{color:#fff;font-weight:700;font-size:16px;}
  #aug-chat .status{color:#9fd8b8;font-size:12.5px;display:flex;align-items:center;gap:5px;}
  #aug-chat .status::before{content:"";width:6px;height:6px;border-radius:50%;background:#2bb673;}
  #aug-chat .close{border:none;background:none;color:#b9c4d6;font-size:22px;cursor:pointer;padding:4px;line-height:1;}
  #aug-chat .close:hover{color:#fff;}
  #aug-chat .expand{border:none;background:none;color:#b9c4d6;cursor:pointer;padding:6px;line-height:0;}
  #aug-chat .expand:hover{color:#fff;}
  #aug-chat .expand svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
  #aug-chat .panel.full{top:0;right:0;bottom:0;left:0;width:auto !important;height:auto !important;max-width:none;max-height:none;border-radius:0;}
  #aug-chat .panel.full .resize{display:none;}
  #aug-chat .panel.full .messages,#aug-chat .panel.full .input-row{width:100%;max-width:860px;margin:0 auto;box-sizing:border-box;}
  #aug-chat .panel.full .input-row{border-top:none;}
  #aug-chat .messages{flex:1;overflow-y:auto;padding:20px 18px;display:flex;flex-direction:column;gap:14px;}
  #aug-chat .msg{max-width:86%;font-size:15px;line-height:1.5;}
  #aug-chat .msg.bot{align-self:flex-start;}
  #aug-chat .msg.user{align-self:flex-end;}
  #aug-chat .bubble{padding:12px 15px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere;}
  #aug-chat .msg.bot .bubble{background:#122e52;color:#edeff3;border-bottom-left-radius:4px;}
  #aug-chat .msg.user .bubble{background:var(--orange);color:#fff;border-bottom-right-radius:4px;}
  #aug-chat .bubble a{color:#ffb48a;}
  #aug-chat .meta{font-size:11.5px;color:#7c8aa0;margin-top:5px;padding:0 3px;}
  #aug-chat .msg.user .meta{text-align:right;}
  #aug-chat .sources{font-size:12px;color:#9aabc4;margin-top:6px;padding:0 3px;overflow-wrap:anywhere;}
  #aug-chat .sources a{color:#ffb48a;text-decoration:underline;}
  #aug-chat .quick{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;}
  #aug-chat .quick button{background:transparent;border:1px solid #2e4c71;color:#cbd6e6;font:inherit;font-size:13px;
    padding:7px 12px;border-radius:20px;cursor:pointer;transition:background .15s ease,border-color .15s ease;}
  #aug-chat .quick button:hover{background:#122e52;border-color:var(--orange);color:#fff;}
  #aug-chat .followup button{margin-top:8px;background:transparent;border:1px solid var(--orange);color:#ffb48a;font:inherit;
    font-size:13px;padding:7px 12px;border-radius:20px;cursor:pointer;}
  #aug-chat .followup button:hover{background:var(--orange);color:#fff;}
  #aug-chat .ai-tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:4px;background:rgba(255,255,255,.12);
    color:#dfe6f1;font-size:11px;font-weight:600;letter-spacing:.04em;vertical-align:2px;}
  #aug-chat .typing .bubble{color:#9aabc4;}
  #aug-chat .card{margin-top:8px;padding:11px 13px;border:1px solid #2e4c71;border-radius:12px;background:#0c1f3c;color:#edeff3;font-size:14px;}
  #aug-chat .card .who{font-weight:700;}
  #aug-chat .card .role{color:#9aabc4;font-size:12.5px;margin-bottom:5px;}
  #aug-chat .card a{color:#ffb48a;display:block;overflow-wrap:anywhere;}
  #aug-chat .card button,#aug-chat .lead .actions button{margin-top:9px;background:var(--orange);border:none;color:#fff;font:inherit;
    font-size:13px;font-weight:600;padding:7px 12px;border-radius:8px;cursor:pointer;}
  #aug-chat .card button:hover,#aug-chat .lead .actions button:hover{background:var(--orange-hi);}
  #aug-chat .lead{margin-top:8px;padding:13px;border:1px solid #2e4c71;border-radius:12px;background:#0c1f3c;color:#edeff3;
    font-size:13.5px;display:flex;flex-direction:column;gap:8px;}
  #aug-chat .lead .title{font-weight:700;font-size:14px;}
  #aug-chat .lead .note{color:#9fb0c8;font-size:12.5px;line-height:1.35;margin:-4px 0 2px;}
  #aug-chat .lead label{display:flex;flex-direction:column;gap:3px;color:#b9c4d6;font-size:12.5px;}
  #aug-chat .lead input[type=text],#aug-chat .lead input[type=email],#aug-chat .lead input[type=tel],#aug-chat .lead textarea{
    background:#071830;border:1px solid #2e4c71;border-radius:8px;color:#fff;font:inherit;font-size:14px;padding:7px 9px;width:100%;}
  #aug-chat .lead textarea{resize:vertical;min-height:54px;}
  #aug-chat .lead input:focus,#aug-chat .lead textarea:focus{outline:2px solid var(--orange);outline-offset:1px;}
  #aug-chat .lead .row{display:flex;gap:8px;}
  #aug-chat .lead .row label{flex:1;min-width:0;}
  #aug-chat .lead .consent{flex-direction:row;align-items:flex-start;gap:8px;color:#cbd6e6;line-height:1.35;}
  #aug-chat .lead .consent input{margin-top:2px;flex:none;}
  #aug-chat .lead .actions{display:flex;gap:8px;align-items:center;}
  #aug-chat .lead .actions button{margin-top:0;}
  #aug-chat .lead .actions button:disabled{opacity:.5;cursor:default;}
  #aug-chat .lead .actions .cancel{background:transparent;border:1px solid #2e4c71;color:#cbd6e6;font-weight:400;}
  #aug-chat .lead .error{color:#ffb48a;font-size:12.5px;}
  #aug-chat .lead .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;}
  #aug-chat .input-row{border-top:1px solid rgba(255,255,255,.08);padding:12px 14px;}
  #aug-chat .field{display:flex;align-items:center;background:#0c1f3c;border-radius:10px;padding:6px 8px 6px 14px;gap:8px;}
  #aug-chat .field input{flex:1;background:none;border:none;outline:none;color:#fff;font:inherit;font-size:15px;padding:8px 0;min-width:0;}
  #aug-chat .field input::placeholder{color:#6f80a3;}
  #aug-chat .send{width:34px;height:34px;border-radius:8px;background:var(--orange);border:none;display:flex;
    align-items:center;justify-content:center;cursor:pointer;flex:none;}
  #aug-chat .send:hover{background:var(--orange-hi);}
  #aug-chat .send:disabled{opacity:.5;cursor:default;}
  #aug-chat .send svg{width:16px;height:16px;fill:#fff;}
  #aug-chat .foot{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:#6a7a97;padding-top:8px;}
  #aug-chat .foot button{background:none;border:none;color:#8aa0c4;font:inherit;font-size:11px;cursor:pointer;padding:0;text-decoration:underline;}
  @media (max-width:460px){
    #aug-chat .panel{right:0;bottom:0;left:0;width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0;}
    #aug-chat .launcher{left:16px;bottom:16px;}
    #aug-chat .resize{display:none;}
    #aug-chat .expand{display:none;}
    #aug-chat .teaser{max-width:200px;}
  }
  @media (prefers-reduced-motion:reduce){#aug-chat .teaser,#aug-chat .panel,#aug-chat .toggle{transition:none;}}`;

  const BUBBLE_ICON = '<path d="M21 11.5c0 4.14-4.03 7.5-9 7.5-1.06 0-2.08-.15-3.02-.43L4 20l1.06-3.18C4.4 15.6 4 14.6 4 13.5 4 9.36 8.03 6 13 6s9 3.36 9 5.5z"/>';
  const GREETING = "Hi! I'm the Auburn Engineering giving assistant, an AI tool. I can help with ways to give, supporting a specific department, the EAGLE Society, or finding the right person on our advancement team.";
  const QUICK = ['How do I make a gift?', 'Can I give to my department?', 'Who can I talk to about a gift?'];

  const root = document.createElement('div');
  root.id = 'aug-chat';
  root.innerHTML = `
    <style>${css}</style>
    <div class="launcher">
      <div class="teaser" role="button" tabindex="0" aria-label="Open chat with the Auburn Engineering giving assistant">
        <button class="teaser-close" aria-label="Dismiss">&times;</button>
        Questions about giving to Auburn Engineering? I can help.
      </div>
      <button class="toggle" aria-label="Open Auburn Engineering giving assistant" aria-haspopup="dialog" aria-expanded="false">
        <span class="ping"></span>
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${BUBBLE_ICON}</svg>
      </button>
    </div>
    <div class="panel" role="dialog" aria-modal="false" aria-label="Auburn Engineering Giving Assistant">
      <div class="resize" title="Drag to resize" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="M2 2 L14 14 M7 2 L14 9 M2 7 L9 14"/></svg></div>
      <div class="head">
        <div class="avatar"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">${BUBBLE_ICON}</svg></div>
        <div class="head-text"><div class="name">Engineering Giving Assistant<span class="ai-tag">AI</span></div><div class="status">AI assistant · Online now</div></div>
        <button class="expand" aria-label="Full screen" title="Full screen"><svg viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg></button>
        <button class="close" aria-label="Close chat">&times;</button>
      </div>
      <div class="messages" aria-live="polite"></div>
      <div class="input-row">
        <div class="field">
          <input type="text" placeholder="Ask about giving to Auburn Engineering..." autocomplete="off" maxlength="1000" aria-label="Your question">
          <button class="send" aria-label="Send message"><svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg></button>
        </div>
        <div class="foot"><span>AI-generated answers from official Auburn Engineering giving pages. Verify details at the linked source.</span><button class="reset" title="Clear this conversation">Clear</button></div>
      </div>
    </div>`;
  document.body.appendChild(root);

  const $ = (sel) => root.querySelector(sel);
  const teaser = $('.teaser'), toggle = $('.toggle'), panel = $('.panel');
  const messages = $('.messages'), input = $('.field input'), sendBtn = $('.send');

  // ---- State: conversation in memory only ----
  const state = { history: [], unanswered: [] };
  function teaserDismissed() {
    try { return sessionStorage.getItem(TEASER_KEY) === '1'; } catch (e) { return false; }
  }
  function dismissTeaser() {
    try { sessionStorage.setItem(TEASER_KEY, '1'); } catch (e) { /* storage unavailable */ }
  }

  // ---- Rendering ----
  function linkify(text) {
    // Build DOM nodes (never innerHTML) so answers can't inject markup.
    const frag = document.createDocumentFragment();
    const re = /https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"]/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      frag.append(text.slice(last, m.index));
      const a = document.createElement('a');
      a.href = m[0]; a.textContent = m[0]; a.target = '_blank'; a.rel = 'noopener';
      frag.append(a);
      last = m.index + m[0].length;
    }
    frag.append(text.slice(last));
    return frag;
  }

  function render(entry, withQuick) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + entry.from;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.append(entry.from === 'bot' ? linkify(entry.text) : entry.text);
    wrap.append(bubble);
    const links = (entry.sources || []).filter((u) => /^https?:\/\//.test(u));
    if (links.length) {
      const src = document.createElement('div');
      src.className = 'sources';
      src.append('Sources: ');
      links.forEach((u, i) => {
        const a = document.createElement('a');
        a.href = u; a.target = '_blank'; a.rel = 'noopener';
        a.textContent = u.replace(/^https?:\/\//, '').replace(/\/$/, '');
        if (i) src.append(' · ');
        src.append(a);
      });
      wrap.append(src);
    }
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = entry.from === 'bot' ? 'Giving Assistant (AI)' : 'You';
    wrap.append(meta);
    (entry.contacts || []).forEach((c) => wrap.append(contactCard(c, wrap)));
    if (entry.offerContact) wrap.append(leadForm(''));
    else if (entry.offerFollowup && !(entry.contacts || []).length) wrap.append(followupOffer(wrap));
    if (withQuick) {
      const q = document.createElement('div');
      q.className = 'quick';
      QUICK.forEach((text) => {
        const b = document.createElement('button');
        b.type = 'button'; b.textContent = text;
        b.addEventListener('click', () => ask(text));
        q.append(b);
      });
      wrap.append(q);
    }
    messages.append(wrap);
    messages.scrollTop = messages.scrollHeight;
    return wrap;
  }

  // A long reply would otherwise be scrolled to its end. Show the visitor's question and the start
  // of the reply instead; if both don't fit, the reply's first line goes to the top.
  function revealReply(question, reply) {
    const box = messages.getBoundingClientRect();
    const from = question && reply.getBoundingClientRect().bottom - question.getBoundingClientRect().top <= box.height
      ? question : reply;
    if (from === question) { messages.scrollTop = messages.scrollHeight; return; }
    messages.scrollTop += reply.getBoundingClientRect().top - box.top - 12;
  }

  // ---- Staff contact cards and the follow-up form ----
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function contactCard(c, wrap) {
    const card = el('div', 'card');
    card.append(el('div', 'who', c.name), el('div', 'role', c.title));
    if (c.email) {
      const a = el('a', '', c.email);
      a.href = 'mailto:' + c.email;
      card.append(a);
    }
    if (c.phone) {
      const a = el('a', '', c.phone);
      a.href = 'tel:' + c.phone.replace(/\D/g, '');
      card.append(a);
    }
    const b = el('button', '', 'Ask ' + c.name.split(' ')[0] + ' to contact me');
    b.type = 'button';
    b.addEventListener('click', () => {
      if (wrap.querySelector('.lead')) return;
      wrap.append(leadForm(c.name));
      messages.scrollTop = messages.scrollHeight;
    });
    card.append(b);
    return card;
  }

  // Shown under a reply the assistant couldn't answer: one button that opens the follow-up form.
  function followupOffer(wrap) {
    const box = el('div', 'followup');
    const b = el('button', '', 'Have a staff member follow up with me');
    b.type = 'button';
    b.addEventListener('click', () => {
      box.replaceWith(leadForm(''));
      messages.scrollTop = messages.scrollHeight;
    });
    box.append(b);
    return box;
  }

  function field(labelText, type, name, required, max) {
    const label = el('label', '', labelText);
    const control = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') control.type = type;
    control.name = name; control.required = required; control.maxLength = max;
    label.append(control);
    return label;
  }

  // staff: the routed staff member's name, or '' for a general request to the giving office.
  function leadForm(staff) {
    const form = el('form', 'lead');
    form.noValidate = true;
    const names = el('div', 'row');
    names.append(field('First name', 'text', 'first_name', true, 80), field('Last name', 'text', 'last_name', true, 80));
    const consent = el('label', 'consent');
    const box = document.createElement('input');
    box.type = 'checkbox'; box.name = 'consent'; box.required = true;
    consent.append(box, 'I agree that Auburn Engineering Advancement may store these details and contact me.');
    // Spam traps: a field hidden from people (bots fill in every field), and the time the form was open.
    const trap = el('div', 'hp');
    trap.setAttribute('aria-hidden', 'true');
    const trapLabel = field('Website', 'text', 'website', false, 200);
    trapLabel.querySelector('input').tabIndex = -1;
    trapLabel.querySelector('input').autocomplete = 'off';
    trap.append(trapLabel);
    const opened = Date.now();
    const error = el('div', 'error');
    error.setAttribute('role', 'alert');
    const actions = el('div', 'actions');
    const submit = el('button', '', 'Send request');
    submit.type = 'submit';
    const cancel = el('button', 'cancel', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', () => form.remove());
    actions.append(submit, cancel);
    form.append(
      el('div', 'title', (staff ? 'Ask ' + staff + ' to follow up' : 'Request a follow-up') + ' (optional)'),
      el('div', 'note', 'Only if you want someone to contact you. You can keep chatting without filling this in.'),
      names,
      field('Email', 'email', 'email', true, 254),
      field('Phone (optional)', 'tel', 'phone', false, 30),
      field('What would you like to discuss? (optional)', 'textarea', 'message', false, 1000),
      consent, trap, error, actions);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!form.checkValidity()) {
        error.textContent = box.checked ? 'Please enter your name and a valid email address.'
          : 'Please tick the box so we can store your details and contact you.';
        return;
      }
      const data = Object.fromEntries(new FormData(form));
      data.consent = true; data.staff = staff; data.seconds_open = (Date.now() - opened) / 1000;
      submit.disabled = true; error.textContent = '';
      try {
        const res = await fetch(CONTACT_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-store',
          body: JSON.stringify(data),
        });
        if (res.status === 429) {
          submit.disabled = false;
          error.textContent = 'Too many requests from this connection. Please try again later, or contact ' + MAIN_CONTACT + '.';
          return;
        }
        if (!res.ok) throw new Error('Backend returned ' + res.status);
        // Replace the form so the details don't stay on screen or in page memory.
        form.replaceWith(el('div', 'card', 'Thank you, ' + data.first_name + '. Your request for ' +
          (staff || 'the Engineering Advancement team') + ' has been received.'));
      } catch (err) {
        console.error('Follow-up request failed:', err);
        submit.disabled = false;
        error.textContent = 'That did not go through. Please try again, or contact ' + MAIN_CONTACT + '.';
      }
    });
    return form;
  }

  function renderAll() {
    messages.textContent = '';
    render({ from: 'bot', text: GREETING }, state.history.length === 0);
    state.history.forEach((e) => render(e));
  }

  // ---- Talking to the backend ----
  async function fetchReply(text, history) {
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({ message: text, history }),
      });
      if (!res.ok) throw new Error('Backend returned ' + res.status);
      const data = await res.json();
      return { from: 'bot', text: (data.answer || '').trim() || FALLBACK_REPLY, sources: data.sources || [],
        contacts: data.contacts || [], offerContact: !!data.offer_contact,
        offerFollowup: !!data.offer_followup, unanswered: data.unanswered || null };
    } catch (err) {
      console.error('Giving assistant request failed:', err);
      return { from: 'bot', text: FALLBACK_REPLY, sources: [], failed: true };
    }
  }

  // ---- Unanswered questions: sent once the visitor is done, then forgotten ----
  let idleTimer = null;
  function reportUnanswered() {
    clearTimeout(idleTimer);
    if (!state.unanswered.length) return;
    // text/plain keeps sendBeacon free of a CORS preflight when the widget is on another origin.
    const body = new Blob([JSON.stringify({ questions: state.unanswered.slice(-20) })], { type: 'text/plain' });
    state.unanswered = [];
    if (!navigator.sendBeacon || !navigator.sendBeacon(UNANSWERED_ENDPOINT, body)) {
      fetch(UNANSWERED_ENDPOINT, { method: 'POST', body, keepalive: true }).catch(() => {});
    }
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') reportUnanswered(); });
  window.addEventListener('pagehide', reportUnanswered);

  let busy = false;
  async function ask(text) {
    text = (text || '').trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    const quick = messages.querySelector('.quick');
    if (quick) quick.remove();
    // Earlier turns for context; connection-error replies aren't part of the conversation.
    const history = state.history.filter((e) => !e.failed).slice(-HISTORY_SENT)
      .map((e) => ({ role: e.from === 'user' ? 'user' : 'assistant', content: e.text }));
    const userEntry = { from: 'user', text };
    state.history.push(userEntry);
    const asked = render(userEntry);
    const typing = render({ from: 'bot', text: 'Typing…' });
    typing.classList.add('typing');
    const reply = await fetchReply(text, history);
    typing.remove();
    if (reply.unanswered) {
      state.unanswered.push(reply.unanswered);
      delete reply.unanswered;
      clearTimeout(idleTimer);
      idleTimer = setTimeout(reportUnanswered, IDLE_REPORT_MS);
    }
    state.history.push(reply);
    revealReply(asked, render(reply));
    busy = false; sendBtn.disabled = false;
    input.focus();
  }

  // ---- Open / close / teaser ----
  function openChat() {
    teaser.classList.remove('show');
    dismissTeaser();
    panel.classList.add('open');
    toggle.setAttribute('aria-expanded', 'true');
    setTimeout(() => input.focus(), 200);
  }
  const expandBtn = $('.expand');
  function setFull(on) {
    panel.classList.toggle('full', on);
    expandBtn.setAttribute('aria-label', on ? 'Exit full screen' : 'Full screen');
    expandBtn.title = on ? 'Exit full screen' : 'Full screen';
    expandBtn.querySelector('svg').innerHTML = on ? '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>' : '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>';
  }
  expandBtn.addEventListener('click', () => { setFull(!panel.classList.contains('full')); input.focus(); });
  function closeChat() {
    reportUnanswered();
    setFull(false);
    panel.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
  }
  toggle.addEventListener('click', () => (panel.classList.contains('open') ? closeChat() : openChat()));
  $('.close').addEventListener('click', closeChat);
  teaser.addEventListener('click', openChat);
  teaser.addEventListener('keydown', (e) => { if (e.key === 'Enter') openChat(); });
  $('.teaser-close').addEventListener('click', (e) => {
    e.stopPropagation();
    dismissTeaser();
    teaser.classList.remove('show');
  });
  // Escape leaves full screen first, then closes the chat.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !panel.classList.contains('open')) return;
    if (panel.classList.contains('full')) setFull(false); else closeChat();
  });

  sendBtn.addEventListener('click', () => { const v = input.value; input.value = ''; ask(v); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const v = input.value; input.value = ''; ask(v); } });
  $('.reset').addEventListener('click', () => { reportUnanswered(); state.history = []; renderAll(); });

  // ---- Drag-to-resize (panel is anchored bottom-left, so the grip is top-right) ----
  const MIN_W = 300, MIN_H = 340;
  let drag = null;
  $('.resize').addEventListener('pointerdown', (e) => {
    if (window.innerWidth <= 460 || panel.classList.contains('full')) return;
    const r = panel.getBoundingClientRect();
    drag = { x: e.clientX, y: e.clientY, w: r.width, h: r.height };
    panel.classList.add('resizing');
    e.preventDefault();
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const w = Math.min(Math.max(drag.w + e.clientX - drag.x, MIN_W), Math.min(640, window.innerWidth - 32));
    const h = Math.min(Math.max(drag.h + drag.y - e.clientY, MIN_H), Math.min(window.innerHeight - 32, 760));
    panel.style.width = w + 'px';
    panel.style.height = h + 'px';
  });
  document.addEventListener('pointerup', () => { drag = null; panel.classList.remove('resizing'); });

  // ---- Start ----
  renderAll();
  if (!teaserDismissed()) setTimeout(() => { if (!panel.classList.contains('open')) teaser.classList.add('show'); }, 1800);
})();
