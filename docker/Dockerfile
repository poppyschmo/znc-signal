# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>

FROM openjdk:16-jdk-alpine
ENV SIGNAL_CLI_VERSION ${SIGNAL_CLI_VERSION:-0.6.11}

ARG signal_cli_home
ENV SIGNAL_CLI_HOME ${signal_cli_home:-/var/lib/signal-cli}
ENV SIGNAL_CLI_OPTS=-Xms2m

ADD src/signal-cli-$SIGNAL_CLI_VERSION.tar.gz /opt/
COPY wrapper.sh /usr/bin/signal-cli

# TODO use system UID > SYS_UID_MIN (also GID)
ARG pwdent=signal-cli:x:99:99:signal-cli:$SIGNAL_CLI_HOME:/sbin/nologin
RUN set -x && \
	ls -alh /opt && \
	test -d $JAVA_HOME && \
	echo $PATH | grep -qF $JAVA_HOME && \
	chmod 775 /opt/signal-cli-$SIGNAL_CLI_VERSION/bin/signal-cli && \
	sed -i '/^nobody/a\'$pwdent /etc/passwd && \
	sed -i '/^nobody/a\signal-cli:x:99:signal-cli' /etc/group && \
	mkdir -p $SIGNAL_CLI_HOME && \
	chown 99:99 $SIGNAL_CLI_HOME && \
	apk add --no-cache dbus supervisor && \
	mkdir -p /etc/dbus-1/system.d \
		/etc/supervisord.d \
		/usr/local/share/supervisord \
		/usr/share/java/signal-cli \
		/var/run/supervisord && \
	chmod 755 /usr/bin/signal-cli

COPY supervisor_share/* /usr/local/share/supervisord/
COPY src/org.asamk.Signal.conf /etc/dbus-1/system.d/
COPY listen_tcp.conf /etc/dbus-1/system.d/

# Asterisk means 0.0.0.0, which is okay here if only on one network
ARG interface_name="*"
ARG port_number=47000
RUN sed -i -e "s/%interface_name%/$interface_name/" \
	-e "s/%port_number%/$port_number/" \
	/etc/dbus-1/system.d/listen_tcp.conf

COPY supervisord.conf /etc/supervisord.conf
COPY debug_profile.sh /etc/profile.d/aliases.sh
RUN ( echo SIGNAL_CLI_VERSION=$SIGNAL_CLI_VERSION \
		SIGNAL_CLI_OPTS=$SIGNAL_CLI_OPTS \
		JAVA_HOME=$JAVA_HOME \
		PATH=$PATH; \
	echo export SIGNAL_CLI_VERSION SIGNAL_CLI_OPTS JAVA_HOME PATH; \
	) >> /etc/profile.d/aliases.sh && \
	mv /etc/profile.d/color_prompt /etc/profile.d/color_prompt.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
	ln -s /entrypoint.sh /usr/local/bin/interact
ENTRYPOINT ["/entrypoint.sh"]
