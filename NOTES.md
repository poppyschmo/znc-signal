## Installation

The recommended setup<sup>[4](#user-content-other_setups)</sup> is to run
both ZNC and signal-cli in networked<sup>[2](#user-content-hostname)</sup>
containers. Your best bets are
- the [official ZNC Docker image][dockerhubznc]
- a signal-cli built from (or based on)<sup>[3](#user-content-image)</sup>
  the provided [`/docker/Dockerfile`](docker/Dockerfile)

Existing signal-cli users should bind a *copy* of their config-data directory
to the appropriate path inside the container.<sup>[5](#user-content-vols)</sup>
New users should instead bind an empty directory or volume.

After securing a dedicated number, new users should proceed with the usual
signal-cli [setup steps][sigcliusage] (typically just
registration/verification).<sup>[6](#user-content-chicken_egg)</sup>

### The ZNC module
1. Clone the repo somewhere convenient
   ```console
   >$ git clone --recurse-submodules \
       https://github.com/poppyschmo/znc-signal.git
   ```
2. Copy the [`/Signal`](Signal) directory to the `/modules` subdirectory of
   the volume to be mounted inside the container
3. Load the ZNC module (remembering the capital "S")

Kubernetes users can do the first two steps in an init container, binding
config maps where necessary. Or, just prepare a dedicated volume ahead of time
and persist the whole `/znc-data` tree.


### Getting a number
Various [options][SigDeskContrib] exist and are worth exploring, including
landlines with voice-based verification. In the meantime, if you have access to
a US mobile number, a Twilio trial<sup>[7](#user-content-twilio_trial)</sup>
can probably hold you over.<sup>[8](#user-content-twilio_period)</sup>


## Caveats
The following aren't so much disclaimers as admissions of shortcomings.

1. The author remains wholly ignorant as to the inner workings of the
   underlying technologies on which this module depends, namely ZNC, IRC,
   D-Bus, and Signal.
2. This module is, for now, solely and fundamentally a learning tool and
   a personal experiment.
3. This module will never be a self-contained, bootstrapped, one-click wonder;
   too many independently moving parts tenuously strung together, any of which
   could render the whole thing inoperable at any time, perhaps indefinitely.
4. Like most experimental, alpha-quality projects, this module is high
   maintenance. Be prepared to manually merge your config, rebuild the
   container, reinstall the module, restart ZNC, etc., on every update.
5. Because this module has only been tried in a few configurations, it should
   be assumed unstable. That means crashes may require restarting Docker
   itself, reloading firewall rules, bouncing network connections, and/or
   rebooting the host machine, all of which introduce security risks. For what
   it's worth, the signal-cli account and those of the Signal clients it
   forwards to are most likely immune from being permanently compromised, so
   long as you own those numbers.
6. For the above reasons, it's not recommended to make this available in
   multi-user ZNC setups or mission-critical operations at this time. In other
   words, although this module's type is "User", for now, it should be
   considered admin-only and single-user only.


## Notes

1. <a name="forwarder"></a> A [mentions][] aggregator like [ZNC Watch][] that
   automatically forwards messages based on match conditions.

2. <a name="hostname"></a> This ZNC module talks to signal-cli using the D-Bus
   protocol over a "local" TCP connection. In simple setups, this means both
   containers should reside on the same "custom" network (i.e., not "bridge").
   ```console
   ># docker network ls --filter type=custom --format '{{ .Name }}'
   ```
   A human-pronounceable hostname should be explicitly assigned, for example,
   using `docker-run`'s `--hostname` option.

   For Kubernetes, disregard the above and just place the two containers in
   the same pod. Exposing (this instance of) signal-cli as a service is not
   recommended.

   Note that the D-Bus TCP transport was deprecated on Unix in 2018
   (see revision 0.33 of the [spec][dbus_spec]).


3. <a name="image"></a> Pulling some random signal-cli image from Docker Hub
   definitely won't work. Also note that various build args like `port_number`
   and `interface_name` may be necessary. If using the
   [`/docker/Makefile`](docker/Makefile) to retrieve the required tarballs, be
   aware that **PGP signatures are not checked**.

4. <a name="other_setups"></a> *Other configurations*. For example, if only
   signal-cli is containerized, you may have to fiddle with the D-Bus
   connection on the host box. Experimenting with the `dbus-send` tool is
   already described in the signal-cli [wiki][sigclidbuswiki]. There's no need
   for numeric IPs if you're able to resolve container names.
   ```console
   ># docker run --detach --env "SIGNAL_CLI_USERNAME=+18662904236" \
       --name signal --hostname signal \
       -v /tmp/config_data:/var/lib/signal-cli/.local/share/signal-cli \
       custom/signal-cli:test

   >$ DBUS_SESSION_BUS_ADDRESS=tcp:host=172.17.0.2,port=47000 \
       dbus-send --print-reply --type=method_call \
       --dest=org.asamk.Signal /org/asamk/Signal \
       org.asamk.Signal.sendMessage string:"Testing" array:string: \
       string:+18883821222

   ```
   If also running signal-cli on the host machine, the transport *must still*
   be TCP, so make certain the interface is local-only.


5. <a name="vols"></a> This example shows `docker-run`'s
   [`--volume` option][dockerrundocs], which takes an argument of
   `HOST-DIR:CONTAINER-DIR`. But the same idea applies to other
   container-creation tools as well as Kubernetes pod definitions.
   ```console
   ># docker run ... \
        --volume HOST-DIR:CONTAINER-DIR ...
                 ↓                ↓
       /some/path/                /var/lib/signal-cli/.local/share/signal-cli/
       └── data/                  └── data/
           ├── +11111111111           ├── +11111111111
           ├── ...                    ├── ...
           └── +99999999999.d/        └── +99999999999.d/
   ```
   The container-side of this mapping can be changed at build time. There's
   nothing special about this container's volume requirements, but the usual
   considerations still apply. For example, when using symlinks, the target
   must be accessible within the container, etc. If `docker-ps` doesn't
   display the current value (because the container is stopped), try
   `docker-container-inspect` instead. These `--format` args may help:
   ```go
   "{{ index .HostConfig.Binds 0 }}"
   // or
   "{{ $m := index .Mounts 0 }}{{ $m.Source }}:{{ $m.Destination }}"
   ```
6. <a name="chicken_egg"></a> The whole *Catch-22* of having to initialize the
   container with an existing account can be sidestepped by providing `--env
   SIGNAL_CLI_USERNAME=<new number>` on the first go-round, even though
   the number's still unregistered. That way, you can use `docker-exec` (or
   `kubectl-exec`) as follows, and forgo having to remake the container:
   ```console
   ># docker exec -it my_container interact

   [my_container:~]$ id && pwd
   uid=99(signal-cli) gid=99(signal-cli) groups=99(signal-cli),99(signal-cli)
   /var/lib/signal-cli

   [my_container:~]$ signal-cli --help
   ...
   ```
   Upon exiting, *restart* the container.

   Note: to access the utility non-interactively, you must first stop the
   service manually:
   ```console
   ># docker exec sigcli_service /entrypoint.sh true
   signal-cli: stopped

   ># docker exec --user signal-cli my_container signal-cli --help
   ...

   ># docker restart my_container
   my_container
   ```

7. <a name="twilio_trial"></a>
   *Twilio trial accounts*.<sup>[a](#user-content-helper)</sup> Requirements:
   a web browser, a working US-mobile number.

   1. [Sign up][twilio_join] for a free trial, add a phone number, and keep
      the web session alive.
   2. Register the number with
      signal-cli,<sup>[b](#user-content-ce_redir)</sup> and keep the console
      session alive.
      ```console
      [my_container:~]$ signal-cli -u $USERNAME register
      ```
   3. Grab the verification code<sup>[c](#user-content-no_bueno)</sup> from
      the latest error report in Twilio's [SMS log][twilio_logs] and enter
      it.
      ```console
      [my_container:~]$ signal-cli -u $USERNAME verify $CODE

      [my_container:~]$ test -n "$(ls .local/share/signal-cli/data)" && echo success
      success
      ```
   4. Notes:
      1. <a name="helper"></a> The [`/twilio_verify`](twilio_verify) helper
         module is an experimental tool unrelated to this process.
      2. <a name="ce_redir"></a> In signal-cli terminology, `USERNAME` means
         phone number. See [above](#user-content-chicken_egg) for info on using
         `docker-exec` to access the container command prompt.
      3. <a name="no_bueno"></a> If you're not receiving messages and have
         previously modified the "Messaging" area of the
         ["phone-numbers"][twilio_incoming] console, ensure the value of the
         `Messaging > A message comes in > webhook` field is non-null (or just
         reset it to the original demo addresss of:
         `https://demo.twilio.com/welcome/sms/`).

8. <a name="twilio_period"></a> (Or be prolonged abusively, if stretching
   dollars is in your current job description.) As a deterrent against
   protracted trials, numbers are currently revoked after a month or so of
   "inactivity."


## Issues, TODOs, etc.
Move these points to individual issues threads (and somehow translate current
ordering/priority). Also collect and consolidate general questions involving
fundamental ZNC and/or SWIG behavior. Possibly do the same for IRC/RFC related
stuff. Add simple, reproducible examples.

1. Add end-to-end tests, with CI, if possible.

1. Investigate the signal-cli "startup delay" issue. Description: the process
   lies dormant for up to 30 minutes before connecting to the message bus;
   it's also delayed in recognizing the first message, incoming or outgoing.
   Search upstream for relevant discussions/activity; perhaps create a DSL or
   shell script demonstrating the issue in a reproducible way. Use a debugger
   or system-call inspector to hunt for clues.

1. Either implement or remove the various "placeholder" config options
   stolen early on from [ZNC Push][]. These are all currently ignored:
   1. `/templates/*/length`
   1. `/conditions/*/replied_only`
   1. `/conditions/*/timeout_post`
   1. `/conditions/*/timeout_push`
   1. `/conditions/*/timeout_idle`

1. Deal with unexpected disconnections from the message bus. Find a way to
   simulate this.

1. Integrate signal-cli 0.6.0 features
   1. Subscribe to and acknowledge receipts
   1. Queue undelivered messages
   1. Alert attached clients or save to context buffers when backlogs arise
   1. Add support for `getGroupIds()`

1. Prepare a TCP/Unix-domain-socket shim for the signal-cli container in case
   some future release of D-Bus drops TCP support entirely.

1. Find some means of testing against real ZNC and signal-cli instances to
   stay abreast of recent developments. Perhaps a move to GitLab would make
   this easier. Although ZNC, Signal, and signal-cli are all on GitHub.

1. Drop support for ZNC 1.7.0 at some target date or with the next minor
   release.


[ZNC Push]: https://github.com/jreese/znc-push
[SigDeskContrib]: https://github.com/signalapp/Signal-Desktop/blob/master/CONTRIBUTING.md#additional-storage-profiles
[dockerhubznc]: https://hub.docker.com/_/znc
[sigcliusage]: https://github.com/AsamK/signal-cli#usage
[sigclidbuswiki]: https://github.com/AsamK/signal-cli/wiki/DBus-service
[interc]: https://interc.pt/2xEcDY3
[dockerrundocs]: https://docs.docker.com/engine/reference/run/#volume-shared-filesystems
[twilio_join]: https://www.twilio.com/try-twilio
[twilio_incoming]: https://www.twilio.com/console/phone-numbers/incoming
[twilio_logs]: https://www.twilio.com/console/sms/logs
[dbus_spec]: https://dbus.freedesktop.org/doc/dbus-specification.html#transports
[mentions]: https://en.wikipedia.org/wiki/Mention_(blogging)
[ZNC Watch]: https://wiki.znc.in/Watch
