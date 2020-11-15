"""
Simulated config data

Deserialized objects should only be used for reference or else made read-only.

Note
    More of these were generated dynamically at import time, but problems arose
    with pytest decorators and circular imports. If revisiting that approach
    for parameterization, should always keep an explicit, readable copy of each
    variant for easy manual checking (rather than just a single "control
    group") as is done here.
"""
from textwrap import indent

json_settings = """\
{
  "host": "example.com",
  "port": 1024,
  "obey": false,
  "auto_connect": true
}"""
json_expressions = """\
{
  "custom": {
    "has": "fixed string"
  },
  "dummy": {
    "all": [
      {
        "wild": "#foo*"
      },
      {
        "! i has": "bar"
      }
    ]
  }
}"""
json_templates = """\
{
  "default": {
    "length": 80,
    "recipients": [
      "+12127365000"
    ]
  }
}"""
json_conditions = """\
{
  "custom": {
    "away_only": true,
    "timeout_post": 360,
    "timeout_idle": 120,
    "x_source": "nick",
    "body": "$custom",
    "source": "$custom"
  },
  "default": {
    "replied_only": true,
    "timeout_push": 600,
    "source": "$dummy",
    "network": "$dummy"
  }
}"""


# TODO replace this with full output in separate file
json_full = """{
  "settings": {\n%s,
  "expressions": {\n%s,
  "templates": {\n%s,
  "conditions": {\n%s
}""" % (*(indent(s.split("\n", 1)[-1], "  ") for
          s in (json_settings, json_expressions,
                json_templates, json_conditions)),)


peeled = {"settings": {"host": "example.com",
                       "port": 1024,
                       "obey": False,
                       "auto_connect": True},
          "expressions": {"custom": {"has": "fixed string"},
                          "dummy": {"all": [{"wild": "#foo*"},
                                            {"! i has": "bar"}]}},
          "templates": {"default": {"length": 80,
                                    "recipients": ["+12127365000"]}},
          "conditions": {"custom": {"away_only": True,
                                    "timeout_post": 360,
                                    "timeout_idle": 120,
                                    "x_source": "nick",
                                    "body": "$custom",
                                    "source": "$custom"},
                         "default": {"replied_only": True,
                                     "timeout_push": 600,
                                     "source": "$dummy",
                                     "network": "$dummy"}}}

ini = """\
[settings]
    host = example.com
    port = 1024
    obey = False
    #authorized = []
    auto_connect = True
    #config_version = 0.3

[expressions]
    custom = {"has": "fixed string"}
    dummy = {"all": [{"wild": "#foo*"}, {"! i has": "bar"}]}
    #pass = {"has": ""}
    #drop = {"! has": ""}

[templates]
    [default]
        recipients = +12127365000
        #format = {focus}{context}: [{nick}] {body}
        #focus_char = U+1F517
        length = 80

[conditions]
    [custom]
        away_only = True
        timeout_post = 360
        timeout_idle = 120
        x_source = nick
        source = $custom
        body = $custom
    [default]
        #enabled = True
        #away_only = False
        #scope = query detached attached
        replied_only = True
        #max_clients = 0
        #timeout_post = 180
        timeout_push = 600
        #timeout_idle = 0
        #template = default
        #x_policy = filter
        #x_source = hostmask
        network = $dummy
        #channel = $pass
        source = $dummy
        #body = $drop
"""

ini_stub_expanded_expressions = """\
[expressions]
    #pass = {"has": ""}
    custom =
        {
          "has": "fixed string"
        }
    dummy =
        {
          "all": [
            {
              "wild": "#foo*"
            },
            {
              "! i has": "bar"
            }
          ]
        }
"""

ini_stub_custom_template = """\
[templates]
    [custom]
        focus_char = \\u2713
    [default]
        recipients = +12127365000
        #format = {focus}{context}: [{nick}] {body}
        #focus_char = U+1F517
        length = 80
"""
