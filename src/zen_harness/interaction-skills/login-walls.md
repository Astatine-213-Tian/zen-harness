# Login walls

Sign-in pages, MFA, CAPTCHAs and payment forms: recognise them, stop, and hand over to the user.

Never type passwords, one-time codes or card numbers, and never solve CAPTCHAs, even if the user pasted them into the chat. The harness drives the user's own Zen, so they can sign in themselves in a few seconds.

## Recognise it

```python
print(js("""return {
  url: location.href,
  password: !!document.querySelector('input[type=password]'),
  otp: !!document.querySelector('input[autocomplete=one-time-code]'),
  captcha: !!document.querySelector('iframe[src*=captcha], iframe[src*=challenge], [class*=captcha]'),
}"""))
```

Other signs: the URL moved to `/login`, `/signin`, `accounts.`, `auth.`; `drain_events()` shows a 401/403 from the site's API; the page asks to "verify you are human".

## Hand over

1. Stop. Don't try another account, a guessed URL, or clearing cookies.
2. Tell the user which site and tab, and ask them to sign in. The tab is in the background; if they want it in front, `activate_tab(current_tab())`.
3. When they say they're done, check the wall is gone and carry on:

```python
goto_url(page_info()["url"])     # reload the page you were on
print(js("!!document.querySelector('input[type=password]')"))   # False once signed in
```

If you need to wait without the user replying, poll for a few minutes at most:

```python
for _ in range(60):
    if not js("!!document.querySelector('input[type=password]')"):
        break
    wait(5)
```

Same for "Continue as ..." OAuth consent screens, payment confirmation, and bank or 3-D Secure pages: the user decides and clicks.
