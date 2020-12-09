FROM docker.io/library/openjdk:17-jdk-slim-bullseye

ENV SIGNAL_CLIENT_VERSION=0.11.0
ENV SIGNAL_CLI_VERSION ${SIGNAL_CLI_VERSION:-0.10.0}

ENV SIGNAL_CLI_HOME /var/lib/signal-cli
ENV SIGNAL_CLI_OPTS=-Xms2m

ADD src/signal-cli-$SIGNAL_CLI_VERSION.tar.gz /opt/
COPY wrapper.sh /usr/bin/signal-cli

RUN set -x && \
	ls -alh /opt && \
	chmod 775 /opt/signal-cli-$SIGNAL_CLI_VERSION/bin/signal-cli && \
	useradd --home-dir $SIGNAL_CLI_HOME \
		--password "" \
		--shell /bin/bash \
		--uid 99 \
		--system --create-home --user-group \
		signal-cli && \
	apt-get update && \
	apt-get install -y --no-install-recommends procps vim-tiny dbus supervisor && \
	mkdir -p /etc/dbus-1/system.d \
		/etc/supervisord.d \
		/usr/local/share/supervisord \
		/usr/share/java/signal-cli \
		/var/run/dbus \
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
	) >> /etc/profile.d/aliases.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
	ln -s /entrypoint.sh /usr/local/bin/interact
ENTRYPOINT ["/entrypoint.sh"]

# vim:ft=dockerfile
