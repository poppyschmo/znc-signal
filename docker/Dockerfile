# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>

FROM openjdk:8-jdk-alpine
ENV SIGNAL_CLI_VERSION ${SIGNAL_CLI_VERSION:-0.6.0}
ENV LIBMATTHEW_VERSION ${LIBMATTHEW_VERSION:-0.8.1}

ARG signal_cli_home
ENV SIGNAL_CLI_HOME ${signal_cli_home:-/var/lib/signal-cli}

ADD src/signal-cli-$SIGNAL_CLI_VERSION.tar.gz /
ADD src/libmatthew-java-$LIBMATTHEW_VERSION.tar.gz /src


# TODO use system UID > SYS_UID_MIN (also GID)
ARG pwdent=signal-cli:x:99:99:signal-cli:$SIGNAL_CLI_HOME:/sbin/nologin
RUN set -x && \
	sed -i '/^nobody/a\'$pwdent /etc/passwd && \
	sed -i '/^nobody/a\signal-cli:x:99:signal-cli' /etc/group && \
	mkdir -p $SIGNAL_CLI_HOME && \
	chown 99:99 $SIGNAL_CLI_HOME && \
	apk add --no-cache bash dbus build-base supervisor && \
	mkdir -p /etc/dbus-1/system.d \
		/var/log/supervisord /var/run/supervisord && \
	cd /src/libmatthew-java-$LIBMATTHEW_VERSION && \
	LIBDIR=$JAVA_HOME/lib/amd64 make install

COPY link_libs.sh /usr/local/bin/
# Ensure all locations in java's library path contain libunix; for now, do so
# explicitly, only using script to verify
RUN chmod 755 /usr/local/bin/link_libs.sh && \
	ln -s ../../../lib/amd64/libunix-java.so $JAVA_HOME/jre/lib/amd64 && \
	ln -s ../libunix-java.so $JAVA_HOME/jre/lib/amd64/server && \
	ln -s $JAVA_HOME/lib/amd64/libunix-java.so /lib && \
	ln -s $JAVA_HOME/lib/amd64/libunix-java.so /usr/lib && \
	/usr/local/bin/link_libs.sh


COPY src/org.asamk.Signal.conf /etc/dbus-1/system.d/
COPY listen_tcp.conf /etc/dbus-1/system.d/
# If mimicking these steps for a non-containerized build, realize that
# asterisk means 0.0.0.0, which is rarely optimal
ARG interface_name="*"
ARG port_number=47000
RUN sed -i -e "s/%interface_name%/$interface_name/" \
	-e "s/%port_number%/$port_number/" \
	/etc/dbus-1/system.d/listen_tcp.conf

COPY supervisord.conf /etc/supervisord.conf

ENV PATH $PATH:/signal-cli-$SIGNAL_CLI_VERSION/bin
RUN cd $SIGNAL_CLI_HOME && \
	echo "declare -x PATH=\$PATH:/signal-cli-$SIGNAL_CLI_VERSION/bin" \
	> .bash_profile && chown 99:99 .bash_profile

# Initial heap size used by upstream /data/signal.service
ENV SIGNAL_CLI_OPTS=-Xms2m
COPY entrypoint.bash /entrypoint.bash
RUN chmod +x /entrypoint.bash && \
	ln -s /entrypoint.bash /usr/local/bin/interact
ENTRYPOINT ["/entrypoint.bash"]
