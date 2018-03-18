"""
Note: for now, all this does is present webhook request data through ZNC's web
interface. It does not automate away any of the trial steps from the README.
In the future, it should allow for on-the-fly issuance/renewal of phone
numbers, along with automated signal-cli registration and verification.

As a placeholder, it does next to nothing and is only marginally helpful if
you're an existing Twilio account holder whose ZNC setup is described by one of
the following:

1. The web interface is publicly accessible and covered by a valid DV cert

2. You're able to graft an arbitrary path from the web interface onto the
   domain's public namespace, e.g. using nginx::

       location /mods/global/twilio_verify/ {
           proxy_pass http://$my_znc_container:8888;
       }
"""
# TODO convert this into a comprehensive signal-cli management module using
# supervisord's XML-RPC API <http://supervisord.org/api.html>. The goal would
# be to never have to deal with signal-cli manually but instead control
# everything through ZNC.

import znc

hook_response = """\
<?xml version="1.0" encoding="UTF-8"?>
<Response>
</Response>
"""

# Poll for changes (like it's 2009)
watch_script = """
var xhr = new XMLHttpRequest();
xhr.onreadystatechange = function() {
  let div = document.querySelector('#watch');
  if (xhr.readyState === 4) {
    let data = JSON.parse(xhr.responseText);
    if (! Object.keys(data).length) {
      div.innerText = 'Listening...';
      return
    }
    div.innerHTML = '<table><tbody></tbody></table>';
    let tbody = document.querySelector("#watch tbody");
    for (let prop in data) {
      if (! data[prop]) continue;
      let tr = document.createElement('tr');
      let th = document.createElement('th');
      let td = document.createElement('td');
      th.textContent = prop;
      td.textContent = data[prop];
      tr.appendChild(th);
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }
};
function update() {
  xhr.open('GET', 'data.json');
  xhr.send();
}
update.id = setInterval(update, 2000);
update();
"""

sc_403 = (403, "Forbidden", "Log in to access this resource.")
sc_404 = (404, "Not Found", "The requested URL was not found on this server.")


class twilio_verify(znc.Module):
    """Serve a do-nothing Twilio listener at a publicly accessible path
    """
    module_types = [znc.CModInfo.GlobalModule]
    query_params = None

    def WebRequiresLogin(self):
        return False

    def ValidateWebRequestCSRFCheck(self, *args, **kwargs):
        # Otherwise, 403 Access Denied and a TypeError
        return True

    def GetWebMenuTitle(self):
        return "twilio_verify"

    def handle_listen(self, WebSock):
        params = "AccountSid To From Body".split()
        is_post = WebSock.IsPost()
        qp = {k: WebSock.GetParam(k, is_post) for k in params}
        self.query_params = dict(filter(lambda i: i[-1], qp.items()))
        WebSock.PrintHeader(len(hook_response), "text/xml")
        WebSock.Write(hook_response)
        if znc.CDebug_Debug():
            print("twilio data: {}".format(self.query_params), flush=True)

    def handle_watch(self, WebSock):
        # XXX doesn't seem like any OnHooks are called for static assets under
        # /modfiles, so can't reject requests from anon sessions without
        # serving dynamically
        WebSock.PrintHeader(len(watch_script), "text/javascript")
        WebSock.Write(watch_script)

    def handle_data(self, WebSock):
        body = "{}"
        if self.query_params:
            import json
            body = json.dumps(self.query_params, separators=(",", ":"))
        WebSock.PrintHeader(len(body), "application/json")
        WebSock.Write(body)

    def OnWebPreRequest(self, WebSock, sPageName):
        if sPageName in ("index", "") and WebSock.IsLoggedIn():
            return False
        try:
            if sPageName == "listen":
                self.handle_listen(WebSock)
            elif sPageName in ("data.json", "watch.js"):
                if not WebSock.IsLoggedIn():
                    WebSock.PrintErrorPage(*sc_403)
                elif sPageName == "data.json":
                    self.handle_data(WebSock)
                elif sPageName == "watch.js":
                    self.handle_watch(WebSock)
            else:
                WebSock.PrintErrorPage(*sc_404)
        finally:
            WebSock.Close()
        return True

    def OnWebRequest(self, WebSock, sPageName, Tmpl):
        if sPageName in ("index", ""):
            return True
