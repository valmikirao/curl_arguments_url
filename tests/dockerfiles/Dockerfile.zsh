# NOTE, this is meant to be built with the source-root as the context
FROM python:3.7-slim

WORKDIR /app

RUN apt-get update && apt-get install -y zsh curl jq git && \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

COPY setup.py /app

RUN pip --no-cache install -e .

COPY . /app

RUN echo 'eval "$(carl utils zsh-print-script)"' >> "$HOME/.zshrc" && \
    echo "export PS1='%% '" >> "$HOME/.zshrc" && \
    mkdir -p "$HOME/.carl/open_api" && \
    cp tests/resources/swagger/openapi-get-args-test.yml "$HOME/.carl/open_api"

CMD ["zsh"]
