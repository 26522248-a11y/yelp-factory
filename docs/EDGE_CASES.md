# Ma trận edge case E-01..E-55

Mỗi ID có handler trong code và một test trỏ tới file thực tế. Chạy toàn bộ:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

| ID | Tình huống | Handler | Test path |
|---|---|---|---|
| E-01 | GPM tắt / port đổi | `adapters/gpm_http.py`, `GPMUnavailable` | `tests/cases/E-01_gpm_down.py` |
| E-02 | CDP không connect được | `adapters/browser.py:attach`, `flows/signup.py:_enter_browser_up` | `tests/cases/E-02_cdp_failure.py` |
| E-03 | Browser chết giữa flow | `core/state_machine.py` resume theo checkpoint | `tests/unit/test_state_machine.py::test_resume_skips_completed_checkpoints` |
| E-04 | Profile đang chạy sẵn | `core/lock.py:AccountLockManager` | `tests/cases/E-04_profile_already_running.py` |
| E-05 | Submit không phản hồi | `flows/signup.py:_enter_submitted` | `tests/cases/E-05_submit_timeout.py` |
| E-06 | Không nhận mail verify | `flows/signup.py:_enter_email_pending` | `tests/cases/E-06_no_verification_mail.py` |
| E-07 | Mail vào spam | `adapters/email.py` quét junkemail | `tests/cases/E-07_junk_folder.py` |
| E-08 | Link verify hết hạn | `MailMessage.looks_expired` | `tests/unit/test_email.py::test_expired_markers` |
| E-09 | Trùng email | `_enter_form_filled` + `_classify_error` | `tests/cases/E-09_email_already_registered.py` |
| E-10 | Proxy chết | `adapters/proxy_probe.py:assert_healthy` | `tests/cases/E-10_proxy_dead.py` |
| E-11 | Proxy chậm | `assert_healthy(slow_p95_s)` | `tests/cases/E-11_proxy_slow.py` |
| E-12 | Geo lệch ZIP | `_enter_proxy_bound` | `tests/cases/E-12_geo_mismatch.py` |
| E-13 | IP bị chặn | `_detect_blocked` | `tests/cases/E-13_ip_blocked.py` |
| E-14 | Yêu cầu phone | `_enter_phone_pending`, machine skip nhánh email | `tests/cases/E-14_phone_required.py` |
| E-15 | OTP sai / hết hạn | `_enter_phone_pending` vòng 3 lần | `tests/cases/E-15_otp_rejected.py` |
| E-16 | SMS không tới | `adapters/sms.py:wait_for_code` | `tests/cases/E-16_sms_not_arriving.py` |
| E-17 | Số đã dùng | `db/models.py:SMSNumber` unique | `tests/cases/E-17_phone_already_used.py` |
| E-18 | Password bị từ chối | `_classify_error` → `password_rejected` | `tests/cases/E-18_password_rejected.py` |
| E-19 | Tên bị từ chối | `_classify_error` → `name_rejected` | `tests/cases/E-19_name_rejected.py` |
| E-20 | `operation_id` conflict | `adapters/gpm_ops.py:ensure_profile` | `tests/cases/E-20_operation_id_conflict.py` |
| E-21 | GPM đổi schema | `GPMSchemaDrift` | `tests/unit/test_gpm_http.py::test_schema_drift_is_detected` |
| E-22 | Hết RAM | `core/governor.py` | `tests/cases/E-22_ram_pressure.py` |
| E-23 | Port debug trùng | `start_profile(remote_debugging_port=...)` | `tests/cases/E-23_debug_port_conflict.py` |
| E-24 | Disk đầy | `core/reaper.py:prune_artifacts` | `tests/cases/E-24_disk_full.py` |
| E-25 | Worker crash | `core/lock.py:reap_stale_locks` | `tests/cases/E-25_worker_crash_lock.py` |
| E-26 | Job dispatch 2 lần | partial unique index `runs` | `tests/cases/E-26_job_dispatched_twice.py` |
| E-27 | Clock skew | `core/guards.py:clock_skew_ok` | `tests/cases/E-27_clock_skew.py` |
| E-28 | Trang tải nửa chừng | `core/guards.py:reload_once` | `tests/cases/E-28_partial_page_load.py` |
| E-29 | Redirect loop | `core/guards.py:RedirectGuard` | `tests/cases/E-29_redirect_loop.py` |
| E-30 | Form đổi layout | `selector_registry/resolver.py` fallback | `tests/cases/E-30_form_layout_drift.py` |
| E-31 | Thiếu field bắt buộc | `_classify_error` + `guess_field_key` | `tests/cases/E-31_missing_required_field.py` |
| E-32 | ZIP không hợp lệ | `_enter_form_filled` + `pick_zip(exclude=)` | `tests/cases/E-32_zip_invalid.py` |
| E-33 | City không được phủ | `flows/pools.py` ZIP pool | `tests/unit/test_pools_and_warmup.py::test_zip_belongs_to_city` |
| E-34 | Domain email bị chặn | `_classify_error` → `email_domain_blocked` | `tests/cases/E-34_email_domain_blocked.py` |
| E-35 | reCAPTCHA v2 | `CaptchaChain`, `detect` | `tests/unit/test_captcha.py` |
| E-36 | v3 score thấp | `core/guards.py:v3_throttle` | `tests/cases/E-36_v3_low_score.py` |
| E-37 | Arkose FunCaptcha | `CapsolverSolver._task_type` | `tests/cases/E-37_arkose.py` |
| E-38 | Solver timeout | `CaptchaChain` fallback | `tests/unit/test_captcha.py::test_falls_back_to_second_solver` |
| E-39 | Token hết hạn | `captcha.token_present` | `tests/cases/E-39_expired_captcha_token.py` |
| E-40 | Overlay che click | `resolver.click(force_after=2)` | `tests/cases/E-40_overlay_blocks_click.py` |
| E-41 | Redirect locale | `_enforce_locale` | `tests/cases/E-41_locale_redirect.py` |
| E-42 | Trang signup redesign | registry `page_tag` | `tests/unit/test_selectors.py::test_page_tag_overrides_base_rules` |
| E-43 | Link verify mở tab mới | `adapters/browser.py:adopt_page` | `tests/cases/E-43_verify_link_new_tab.py` |
| E-44 | Verify nhưng chưa login | `_enter_email_verified` | `tests/cases/E-44_verified_not_logged_in.py` |
| E-45 | Domain chết hàng loạt | `core/guards.py:DomainHealth` | `tests/cases/E-45_domain_blocked.py` |
| E-46 | Field lạ | `guess_field_key` | `tests/cases/E-46_unknown_field.py` |
| E-47 | Suspend ngay sau đăng ký | `_enter_submitted` → SUSPENDED | `tests/cases/E-47_suspended_after_signup.py` |
| E-48 | Captcha lặp sau submit | `_enter_submitted` solve tại chỗ | `tests/cases/E-48_captcha_after_submit.py` |
| E-49 | Onboarding bước lạ | `_enter_onboarded` tối đa 5 bước | `tests/cases/E-49_unknown_onboarding_step.py` |
| E-50 | Session bị logout | `flows/reauth.py` | `tests/cases/E-50_session_logout.py` |
| E-51 | Rate limit 429 | `core/budget.py:penalize` | `tests/unit/test_budget.py::test_429_penalty_halves_the_budget` |
| E-52 | Review bị filter | `core/guards.py:ReviewTracker` | `tests/cases/E-52_review_filtered.py` |
| E-53 | Trùng nội dung review | `flows/warmup.py:ReviewGenerator` | `tests/cases/E-53_duplicate_review.py` |
| E-54 | Registry miss toàn cục | `selector_registry/resolver.py:registry_health` | `tests/cases/E-54_selector_miss_alert.py` |
| E-55 | Yelp đổi URL | `core/guards.py:navigate_via_search` | `tests/cases/E-55_url_changed.py` |

## Tổng hợp

* 55/55 ID có handler + test xanh.
* DB-backed case (E-04, E-17, E-20, E-25, E-26) tự skip nếu Postgres không sẵn sàng.
* Scheduler warming: `tests/integration/test_scheduler.py`.
