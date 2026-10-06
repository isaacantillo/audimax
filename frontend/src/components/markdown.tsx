import ReactMarkdown from 'react-markdown'

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: (p) => <h2 className="mt-4 mb-2 text-xl font-semibold" {...p} />,
        h2: (p) => <h3 className="mt-4 mb-2 text-lg font-semibold" {...p} />,
        h3: (p) => <h4 className="mt-3 mb-1 font-semibold" {...p} />,
        p: (p) => <p className="my-2 leading-relaxed" {...p} />,
        ul: (p) => <ul className="my-2 list-disc space-y-1 pl-6" {...p} />,
        ol: (p) => <ol className="my-2 list-decimal space-y-1 pl-6" {...p} />,
        strong: (p) => <strong className="font-semibold" {...p} />,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
