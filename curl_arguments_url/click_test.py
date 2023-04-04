import os

# @click.group()
# def main():
#     print('main')
#
#
# @main.command(name='http://that.com')
# def this_dot_com():
#     print('http etc')
#
#
COMPLETES = [
    ('http\\://this.com/{foo}', 'A url'),
    ('something with spaces', 'something with spaces'),
    ('foo', 'A description:{frank}'),
    ('food', 'Food, yes')
]


def main():
    comp_words = os.environ.get('COMP_WORDS').split(' ')
    comp_cword = int(os.environ.get('COMP_CWORD'))
    word_to_complete = comp_words[comp_cword]
    complete = os.environ.get('_CLICK_TEST_COMPLETE')
    # with open('/Users/valmikirao/tmp/click-auto-out.txt', 'a') as f:
    #     print('comp_words', 'comp_cword', 'complete', file=f)
    #     print(comp_words, comp_cword, complete, file=f)

    if not complete:
        print('Other main')
    else:
        for key, descr in COMPLETES:
            if key.startswith(word_to_complete):
                print("plain")
                print(key)
                print(descr)


if __name__ == '__main__':
    main()
