import pandas as pd

def parse_mutations(*raw):
    """Parse strings about mutations in this format:
        
        (Chain_)original|residue number|new residue

    Specifying the chain is optional when dealing with a monomer. 1-letter
    aminoacid codes should be used. Multiple mutations should be separated by
    comma.
    Examples:
        
        A_C29S: Chain A, the 29th residue is a cystein and should be replaced
                by serine

        F114A: the 114th residue is a phenylalanine which will be changed to a
               alanine.

    Returns a pandas Dataframe with information about chain, original
    residue, residue number and new residue.
    """
    MutFrame = pd.DataFrame
    for r in raw:

