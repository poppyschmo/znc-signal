# XXX minimally tried, only basic tests, so far
#
# The time-based constraints were stolen from ZNC-Push, but they're
# merely placeholders, for now. <https://wiki.znc.in/Push>
#
# NOTE tracebacks for any exceptions raised here immediately follow the
# caller's "relevant args" dump in the log, so there's no need for
# descriptive assertion messages.
#
APPROVE = True
REJECT = FILTER = False


def expressed(path, maybe_expr, string, expressions, cond_options):
    from .lexpresser import expand_subs, eval_boolish_json
    try:
        expr = expand_subs(maybe_expr, expressions)
        return eval_boolish_json(expr, string)
    except Exception as exc:
        cond_options["enabled"] = False
        raise ValueError(
            "Problem loading {path} {maybe_expr!r}; Disabling condition"
        ) from exc


def wreck_one(name, cond, data, config, debug):
    if debug:
        reason = data["reckoning"]
        reason.append(f"<{name}")
    #
    # Normal options (filters) ----------------------------------------
    #
    # enabled
    if not cond["enabled"]:
        if debug:
            reason.append("enabled>")
        return REJECT
    # away
    if cond["away_only"] and not data["away"]:
        if debug:
            reason.append("away_only>")
        return REJECT
    # scope
    channel = data["channel"]
    detached = data["detached"]
    if ((channel and (("detached" not in cond["scope"]
                       and detached) or
                      ("attached" not in cond["scope"]
                       and not detached))
         or (not channel and "query" not in cond["scope"]))):
        if debug:
            reason.append("scope>")
        return REJECT
    # clients
    client_count = data["client_count"]
    if client_count:
        max_clients = cond["max_clients"]  # 0 ~~> +inf
        if max_clients and max_clients < client_count:
            if debug:
                reason.append("max_clients>")
            return REJECT
    #
    # Expression-based options ----------------------------------------
    #
    # base operation for aggregating expressions (otherwise FILTER)
    disposition = cond["x_policy"] in ("first", "any", "or")
    if debug:
        dism = disposition and "{}!>" or "!{}>"
    # network
    network = data["network"]
    if network:
        path = f"/conditions/{name}/network"
        expr_key = cond["network"]
        if disposition is expressed(path, expr_key, network,
                                    config.expressions, cond):
            if debug:
                reason.append(dism.format("network"))
            return disposition
    # channel
    channel = data["channel"]
    if channel is not None:
        path = f"/conditions/{name}/channel"
        expr_key = cond["channel"]
        if disposition is expressed(path, expr_key, channel,
                                    config.expressions, cond):
            if debug:
                reason.append(dism.format("channel"))
            return disposition
    # source
    source = data[cond["x_source"]]
    if source:
        path = f"/conditions/{name}/source"
        expr_key = cond["source"]
        if disposition is expressed(path, expr_key, source,
                                    config.expressions, cond):
            if debug:
                reason.append(dism.format("source"))
            return disposition
    # body (message body)
    body = data["body"]
    assert body is not None
    path = f"/conditions/{name}/body"
    expr_key = cond["body"]
    if disposition is expressed(path, expr_key, body,
                                config.expressions, cond):
        if debug:
            reason.append(dism.format("body"))
        return disposition
    #
    if disposition is FILTER:
        if debug:
            reason.append("&>")  # FILTER
        return APPROVE
    if debug:
        reason.append("|>")  # FIRST


def reckon(config, data, debug=False):
    """Run conditions checks against normalized hook data

    If multiple conditions exist, they're OR'd together following
    the config's ordering, though "default" aways runs last.
    Non-expressions-based options are collectively AND'd, .e.g.,
    "away_only", "timeout_*", etc. "x_policy" determines the
    global operation for expressions-based options like "source",
    "body", etc.
    """
    if debug:
        data.setdefault("reckoning", []).clear()
    if not config:
        if debug:
            data["reckoning"] += ["No config loaded"]
        return False
    #
    for cond_name, cond_options in config.conditions.items():
        if wreck_one(cond_name, cond_options, data, config, debug):
            data["template"] = cond_options["template"]
            return APPROVE  # <- conditions are OR'd together
    return REJECT
