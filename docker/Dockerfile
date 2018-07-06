# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>

FROM openjdk:8-jdk-alpine
ENV SIGNAL_CLI_VERSION ${SIGNAL_CLI_VERSION:-0.6.0}
ENV LIBMATTHEW_VERSION ${LIBMATTHEW_VERSION:-0.8.1}

ARG signal_cli_home
ENV SIGNAL_CLI_HOME ${signal_cli_home:-/var/lib/signal-cli}

ADD src/signal-cli-$SIGNAL_CLI_VERSION.tar.gz /src
ADD src/libmatthew-java-$LIBMATTHEW_VERSION.tar.gz /src

ARG unixver=0.5

COPY link_libs.sh /usr/local/bin/
COPY wrapper.sh /usr/bin/signal-cli

# TODO use system UID > SYS_UID_MIN (also GID)
ARG pwdent=signal-cli:x:99:99:signal-cli:$SIGNAL_CLI_HOME:/sbin/nologin
RUN set -x && \
	sed -i '/^nobody/a\'$pwdent /etc/passwd && \
	sed -i '/^nobody/a\signal-cli:x:99:signal-cli' /etc/group && \
	mkdir -p $SIGNAL_CLI_HOME && \
	chown 99:99 $SIGNAL_CLI_HOME && \
	apk add --no-cache bash dbus build-base supervisor && \
	mkdir -p /etc/dbus-1/system.d \
		/etc/supervisord.d \
		/usr/local/share/supervisord \
		/usr/share/java/libmatthew \
		/usr/share/java/signal-cli \
		/var/run/supervisord && \
	cd /src/libmatthew-java-$LIBMATTHEW_VERSION && \
	sed -i 's/-source 1\.5/-source 1.6/' Makefile && \
	make unix-$unixver.jar libunix-java.so && \
	install -m 644 unix-$unixver.jar /usr/share/java/libmatthew && \
	install -m 755 libunix-java.so /usr/lib && \
	ln -s unix-$unixver.jar /usr/share/java/libmatthew/unix.jar && \
	chmod 755 /usr/local/bin/link_libs.sh && \
	/usr/local/bin/link_libs.sh && \
	chmod 755 /usr/bin/signal-cli && \
	install -m 644 /src/signal-cli-$SIGNAL_CLI_VERSION/lib/* \
		/usr/share/java/signal-cli/ && \
	rm -f /usr/share/java/signal-cli/unix*.jar

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

# Initial heap size used by upstream /data/signal.service
ENV SIGNAL_CLI_OPTS=-Xms2m
COPY entrypoint.bash /entrypoint.bash
RUN chmod +x /entrypoint.bash && \
	ln -s /entrypoint.bash /usr/local/bin/interact
ENTRYPOINT ["/entrypoint.bash"]
