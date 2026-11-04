# Ma trận edge case E-01..E-55

Cột **test path** trỏ tới file test thực tế. `—` nghĩa là handler đã có nhưng test chưa viết
(trạng thái được cập nhật khi bổ sung). Đây là nguồn sự thật cho Definition of Done.

| ID | Handler | Test path | Trạng thái |
|---|---|---|---|
| E-01 | `adapters/gpm_http.py:health`, `GPMUnavailable` | `tests/cases/E-01_gpm_down.py` | ✅ |
| E-02 | `adapters/browser.py:attach`, `flows/signup.py:_enter_browser_up` | `tests/cases/E-02_cdp_failure.py` | ✅ |
| E-03 | `core/state_machine.py` (resume theo checkpoint) | `tests/unit/test_state_machine.py::test_resume_skips_completed_checkpoints` | ✅ |
| E-04 | `core/lock.py:AccountLockManager` | — | ⏳ |
| E-05 | `flows/signup.py:_enter_submitted` | `tests/cases/E-05_submit_timeout.py` | ✅ |
| E-06 | `flows/signup.py:_enter_email_pending` | — | ⏳ |
| E-07 | `adapters/email.py` (INBOX + junkemail) | `tests/cases/E-07_junk_folder.py` | ✅ |
| E-08 | `MailMessage.looks_expired` → `verify_expired` | `tests/unit/test_email.py::test_expired_markers` | ✅ |
| E-09 | `flows/signup.py:_enter_form_filled` (email_taken) | — | ⏳ |
| E-10 | `adapters/proxy_probe.py:assert_healthy` | — | ⏳ |
| E-11 | `proxy_probe` latency guard | — | ⏳ |
| E-12 | `flows/signup.py:_enter_proxy_bound` | `tests/cases/E-12_geo_mismatch.py` | ✅ |
| E-13 | `flows/signup.py:_detect_blocked` | — | ⏳ |
| E-14 | `flows/signup.py:_enter_phone_pending` + `core/state_machine.py` skip nhánh email | `tests/cases/E-14_phone_required.py` | ✅ |
| E-15 | `adapters/sms.py` (OTP retry) | — | ⏳ |
| E-16 | `adapters/sms.py:wait_for_code` timeout | — | ⏳ |
| E-17 | `db/models.py:SMSNumber.used_by_account` | — | ⏳ |
| E-18 | `_classify_error` → `password_rejected` | — | ⏳ |
| E-19 | `_classify_error` → `name_rejected` | — | ⏳ |
| E-20 | `adapters/gpm_ops.py:ensure_profile` | `tests/unit/test_gpm_http.py::test_success_false_conflict` | ✅ (transport) |
| E-21 | `GPMSchemaDrift` | `tests/unit/test_gpm_http.py::test_schema_drift_is_detected` | ✅ |
| E-22 | `core/governor.py` | — | ⏳ |
| E-23 | `_enter_browser_up` random port retry | — | ⏳ |
| E-24 | `core/reaper.py:ensure_disk_space` | — | ⏳ |
| E-25 | `core/lock.py:reap_stale_locks` | — | ⏳ (cần DB) |
| E-26 | `db/models.py:uq_runs_one_running_per_account` | — | ⏳ (cần DB) |
| E-27 | clock skew check | — | ⏳ |
| E-28 | reload/networkidle | — | ⏳ |
| E-29 | redirect loop | — | ⏳ |
| E-30 | `selector_registry/resolver.py` | `tests/cases/E-30_form_layout_drift.py` | ✅ |
| E-31 | `_classify_error` → `form_drift` | — | ⏳ |
| E-32 | `_classify_error` → `zip_invalid` | — | ⏳ |
| E-33 | `flows/pools.py` ZIP pool | `tests/unit/test_pools_and_warmup.py::test_zip_belongs_to_city` | ✅ |
| E-34 | `_classify_error` → `email_domain_blocked` | — | ⏳ |
| E-35 | `adapters/captcha.py:CaptchaChain` | `tests/unit/test_captcha.py` | ✅ (chain) |
| E-36 | v3 score path (`minScore`) | — | ⏳ |
| E-37 | Arkose task type | — | ⏳ |
| E-38 | `CaptchaChain` fallback solver | `tests/unit/test_captcha.py::test_falls_back_to_second_solver` | ✅ |
| E-39 | `captcha.token_present` | `tests/cases/E-39_expired_captcha_token.py` | ✅ |
| E-40 | `resolver.click(force_after=2)` | `tests/cases/E-40_overlay_blocks_click.py` | ✅ |
| E-41 | `flows/signup.py:_enforce_locale` | — | ⏳ |
| E-42 | `page_tag` registry | `tests/unit/test_selectors.py::test_page_tag_overrides_base_rules` | ✅ |
| E-43 | `adapters/browser.py:adopt_page` | `tests/cases/E-43_verify_link_new_tab.py` | ✅ |
| E-44 | `flows/signup.py:_enter_email_verified` | — | ⏳ |
| E-45 | `db/models.py:EmailDomain.disabled_until` | — | ⏳ |
| E-46 | `selector_registry/resolver.py:guess_field_key` | `tests/cases/E-46_unknown_field.py` | ✅ |
| E-47 | `_enter_submitted` → SUSPENDED | — | ⏳ |
| E-48 | captcha lặp sau submit | — | ⏳ |
| E-49 | `flows/onboarding.py` skip 5 bước | — | ⏳ |
| E-50 | `flows/reauth.py` | — | ⏳ |
| E-51 | `core/budget.py:penalize` | `tests/unit/test_budget.py::test_429_penalty_halves_the_budget` | ✅ |
| E-52 | review filter tracking | — | ⏳ |
| E-53 | `flows/warmup.py:ReviewGenerator` | `tests/cases/E-53_duplicate_review.py` | ✅ |
| E-54 | `selector_registry/resolver.py:registry_health` | `tests/cases/E-54_selector_miss_alert.py` | ✅ |
| E-55 | fallback qua search bar | — | ⏳ |

## Tổng hợp

* 19/55 edge case có test xanh.
* 36 case còn lại đã có handler ở mức khung (hoặc một phần), cần bổ sung test + hoàn thiện xử lý.
* Coverage hiện tại: `pytest --cov=src/core --cov=src/flows` (xem README mục Test).
