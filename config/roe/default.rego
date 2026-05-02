# WASA Rules of Engagement — OPA scope enforcement policy
#
# Every outbound HTTP request and target file access is validated against
# this policy before execution. Deny-by-default.
#
# Phase 2: deployed alongside OPA service. Phase 1 uses path-based
# checks in Python (roe.py:validate_target_path).

package roe

import rego.v1

default allow := false

allow if {
    url_in_scope
    not url_in_denylist
    not action_prohibited
    within_time_window
}

url_in_scope if {
    some pattern in input.roe.scope_allowlist
    glob.match(pattern, ["/"], input.url)
}

url_in_denylist if {
    some pattern in input.roe.scope_denylist
    glob.match(pattern, ["/"], input.url)
}

action_prohibited if {
    some action in input.roe.prohibited_actions
    contains(lower(input.action), lower(action))
}

within_time_window if {
    input.roe.time_window_utc == null
}

within_time_window if {
    input.roe.time_window_utc != null
    time.now_ns() >= time.parse_rfc3339_ns(split(input.roe.time_window_utc, "/")[0])
    time.now_ns() <= time.parse_rfc3339_ns(split(input.roe.time_window_utc, "/")[1])
}
