# NOTE, this is meant to be built with the source-root as the context
FROM python:3.7-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl jq

COPY setup.py /app

RUN pip --no-cache install -e .

COPY . /app

RUN echo 'eval "$(carl utils bash-print-script)"' >> "$HOME/.bashrc" && \
    echo "export PS1='$ '" >> "$HOME/.bashrc" && \
    mkdir -p "$HOME/.carl/open_api" && \
    cp tests/resources/swagger/openapi-get-args-test.yml "$HOME/.carl/open_api"

CMD ["bash"]
